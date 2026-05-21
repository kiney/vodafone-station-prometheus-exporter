from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import sqlite3

from .docsis import DocsisStatus


def write_snapshot(snapshot_dir: Path, scraped_at: datetime, raw: str) -> Path:
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    path = snapshot_dir / f"DOCSIS_{scraped_at.isoformat(timespec='seconds')}"
    path.write_text(raw, encoding="utf-8")
    return path


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
