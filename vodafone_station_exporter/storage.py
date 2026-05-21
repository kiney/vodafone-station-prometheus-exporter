from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import sqlite3

from .docsis import DocsisStatus


def write_snapshot(snapshot_dir: Path, scraped_at: datetime, content: str) -> Path:
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    path = snapshot_dir / f"DOCSIS_{scraped_at.isoformat(timespec='seconds')}"
    path.write_text(content, encoding="utf-8")
    return path


def render_snapshot(status: DocsisStatus) -> str:
    lines = [
        "DOCSIS Status",
        "Verschaffen Sie sich einen Überblick über alle DOCSIS-Parameter Ihres Routers.",
        "Downstream-Kanäle",
        "Kanal ID \tKanaltyp \tFrequenz (MHz) \tModulation \tEmpf. Signalstärke (dBmV/dBµV) \tSNR/MER (dB) \tLock Status",
    ]
    for channel in status.downstream:
        lines.append(
            "\t".join(
                [
                    channel.channel_id,
                    channel.channel_type,
                    channel.frequency_mhz,
                    channel.modulation,
                    _power(channel.power_dbmv, channel.power_dbuv),
                    _number(channel.snr_db),
                    "JA" if channel.locked else channel.lock_status,
                ]
            )
        )
    lines.extend(
        [
            "Upstream-Kanäle",
            "Kanal ID \tKanaltyp \tFrequenz (MHz) \tModulation \tSend. Signalstärke (dBmV/dBµV) \tRanging Status",
        ]
    )
    for channel in status.upstream:
        lines.append(
            "\t".join(
                [
                    channel.channel_id,
                    channel.channel_type,
                    channel.frequency_mhz,
                    channel.modulation,
                    _power(channel.power_dbmv, channel.power_dbuv),
                    _ranging_status(channel.ranging_status),
                ]
            )
        )
    return "\n".join(lines) + "\n"


def _power(dbmv: float | None, dbuv: float | None) -> str:
    return f"{_number(dbmv)}/{_number(dbuv)}"


def _number(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:g}"


def _ranging_status(value: str) -> str:
    if value.casefold() in {"completed", "success", "successful"}:
        return "Erfolgreich"
    return value


class SqliteLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def record(self, scraped_at: datetime, status: DocsisStatus | None, error: str | None) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                INSERT INTO scrapes(scraped_at, success, error, downstream_count, upstream_count, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    scraped_at.isoformat(),
                    1 if status is not None and error is None else 0,
                    error,
                    len(status.downstream) if status else 0,
                    len(status.upstream) if status else 0,
                    json.dumps(asdict(status), ensure_ascii=False) if status else None,
                ),
            )

    def _init_db(self) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scrapes(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scraped_at TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    error TEXT,
                    downstream_count INTEGER NOT NULL,
                    upstream_count INTEGER NOT NULL,
                    payload_json TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_scrapes_scraped_at ON scrapes(scraped_at)")
