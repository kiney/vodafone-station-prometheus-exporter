from __future__ import annotations

from contextlib import closing
from datetime import datetime
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
        with closing(sqlite3.connect(self.path)) as conn:
            with conn:
                conn.execute("PRAGMA foreign_keys = ON")
                cursor = conn.execute(
                    """
                    INSERT INTO scrapes(scraped_at, success, error, downstream_count, upstream_count)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        scraped_at.isoformat(),
                        1 if status is not None and error is None else 0,
                        error,
                        len(status.downstream) if status else 0,
                        len(status.upstream) if status else 0,
                    ),
                )
                scrape_id = cursor.lastrowid
                if status is None:
                    return
                conn.executemany(
                    """
                    INSERT INTO downstream_channels(
                        scrape_id, channel_id, channel_type, frequency_mhz, modulation,
                        power_dbmv, power_dbuv, snr_db, locked, lock_status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            scrape_id,
                            channel.channel_id,
                            channel.channel_type,
                            channel.frequency_mhz,
                            channel.modulation,
                            channel.power_dbmv,
                            channel.power_dbuv,
                            channel.snr_db,
                            1 if channel.locked else 0,
                            channel.lock_status,
                        )
                        for channel in status.downstream
                    ],
                )
                conn.executemany(
                    """
                    INSERT INTO upstream_channels(
                        scrape_id, channel_id, channel_type, frequency_mhz, modulation,
                        power_dbmv, power_dbuv, ranging_success, ranging_status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            scrape_id,
                            channel.channel_id,
                            channel.channel_type,
                            channel.frequency_mhz,
                            channel.modulation,
                            channel.power_dbmv,
                            channel.power_dbuv,
                            1 if channel.ranging_success else 0,
                            channel.ranging_status,
                        )
                        for channel in status.upstream
                    ],
                )

    def _init_db(self) -> None:
        with closing(sqlite3.connect(self.path)) as conn:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS scrapes(
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        scraped_at TEXT NOT NULL,
                        success INTEGER NOT NULL,
                        error TEXT,
                        downstream_count INTEGER NOT NULL,
                        upstream_count INTEGER NOT NULL
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_scrapes_scraped_at ON scrapes(scraped_at)")
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS downstream_channels(
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        scrape_id INTEGER NOT NULL REFERENCES scrapes(id) ON DELETE CASCADE,
                        channel_id TEXT NOT NULL,
                        channel_type TEXT NOT NULL,
                        frequency_mhz TEXT NOT NULL,
                        modulation TEXT NOT NULL,
                        power_dbmv REAL,
                        power_dbuv REAL,
                        snr_db REAL,
                        locked INTEGER NOT NULL,
                        lock_status TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_downstream_channels_scrape_id
                    ON downstream_channels(scrape_id)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_downstream_channels_channel_id
                    ON downstream_channels(channel_id)
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS upstream_channels(
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        scrape_id INTEGER NOT NULL REFERENCES scrapes(id) ON DELETE CASCADE,
                        channel_id TEXT NOT NULL,
                        channel_type TEXT NOT NULL,
                        frequency_mhz TEXT NOT NULL,
                        modulation TEXT NOT NULL,
                        power_dbmv REAL,
                        power_dbuv REAL,
                        ranging_success INTEGER NOT NULL,
                        ranging_status TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_upstream_channels_scrape_id
                    ON upstream_channels(scrape_id)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_upstream_channels_channel_id
                    ON upstream_channels(channel_id)
                    """
                )
