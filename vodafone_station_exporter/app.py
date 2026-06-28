from __future__ import annotations

from datetime import datetime
import json
import logging
import signal
import threading
from zoneinfo import ZoneInfo

from flask import Flask, Response, jsonify
from werkzeug.serving import make_server

from .config import Config
from .docsis import DocsisStatus, parse_docsis_json, parse_docsis_status
from .metrics import render_metrics
from .scraper import RouterScraper
from .storage import SqliteLog, render_snapshot, write_snapshot


LOGGER = logging.getLogger(__name__)


class ExporterState:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.scraper = RouterScraper(config)
        self.sqlite = SqliteLog(config.sqlite_path) if config.sqlite_path else None
        self.lock = threading.Lock()
        self.last_status: DocsisStatus | None = None
        self.last_raw: str | None = None
        self.last_scraped_at: datetime | None = None
        self.last_error: str | None = "not scraped yet"

    def scrape(self) -> None:
        scraped_at = datetime.now(ZoneInfo("Europe/Berlin")).astimezone()
        status: DocsisStatus | None = None
        raw: str | None = None
        error: str | None = None
        try:
            result = self.scraper.fetch_docsis()
            raw = result.body
            status = _parse_raw_status(raw)
            if status.total_channels == 0:
                raise ValueError("DOCSIS page fetched but no channels were parsed")
            if self.config.snapshots_enabled:
                write_snapshot(self.config.snapshot_dir, scraped_at, render_snapshot(status))
            LOGGER.info("scraped %s DOCSIS channels from %s", status.total_channels, result.url)
        except Exception as exc:
            error = str(exc)
            LOGGER.warning("scrape failed: %s", error)

        if self.sqlite:
            self.sqlite.record(scraped_at, status, error)

        with self.lock:
            self.last_status = status
            self.last_raw = raw
            self.last_scraped_at = scraped_at
            self.last_error = error

    def snapshot(self) -> tuple[DocsisStatus | None, datetime | None, str | None]:
        with self.lock:
            return self.last_status, self.last_scraped_at, self.last_error


def create_app(config: Config) -> Flask:
    app = Flask(__name__)
    state = ExporterState(config)
    app.config["EXPORTER_STATE"] = state

    @app.get("/metrics")
    def metrics() -> Response:
        status, scraped_at, error = state.snapshot()
        return Response(render_metrics(status, scraped_at, error), mimetype="text/plain; version=0.0.4; charset=utf-8")

    @app.get("/healthz")
    def healthz() -> Response:
        status, scraped_at, error = state.snapshot()
        code = 200 if status is not None and error is None else 503
        return jsonify({"ok": code == 200, "last_scraped_at": scraped_at.isoformat() if scraped_at else None, "error": error}), code

    @app.post("/scrape")
    def scrape_now() -> Response:
        state.scrape()
        status, scraped_at, error = state.snapshot()
        code = 200 if status is not None and error is None else 502
        return jsonify({"ok": code == 200, "last_scraped_at": scraped_at.isoformat() if scraped_at else None, "error": error}), code

    return app


def start_background_scraper(state: ExporterState) -> threading.Event:
    stop_event = threading.Event()

    def run() -> None:
        while not stop_event.is_set():
            state.scrape()
            stop_event.wait(state.config.interval)

    thread = threading.Thread(target=run, name="docsis-scraper", daemon=True)
    thread.start()
    return stop_event


def run_daemon(config: Config) -> None:
    app = create_app(config)
    state = app.config["EXPORTER_STATE"]
    stop_event = start_background_scraper(state)
    server = make_server(config.host, config.port, app)

    def shutdown(signum: int, frame: object) -> None:
        _request_shutdown(stop_event, server, signum)

    previous_sigterm = signal.signal(signal.SIGTERM, shutdown)
    previous_sigint = signal.signal(signal.SIGINT, shutdown)
    try:
        server.serve_forever()
    finally:
        stop_event.set()
        signal.signal(signal.SIGTERM, previous_sigterm)
        signal.signal(signal.SIGINT, previous_sigint)


def _request_shutdown(stop_event: threading.Event, server: object, signum: int) -> threading.Thread:
    LOGGER.info("received signal %s, shutting down", signum)
    stop_event.set()
    thread = threading.Thread(target=server.shutdown, name="http-shutdown", daemon=True)
    thread.start()
    return thread


def _parse_raw_status(raw: str) -> DocsisStatus:
    try:
        payload = json.loads(raw)
    except ValueError:
        return parse_docsis_status(raw)
    if isinstance(payload, dict):
        return parse_docsis_json(payload)
    return parse_docsis_status(raw)
