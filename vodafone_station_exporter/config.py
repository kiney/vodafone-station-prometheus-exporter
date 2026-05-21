from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


DEFAULT_DOCSIS_PATH = "/api/v1/sta_docsis_status"


@dataclass(frozen=True)
class Config:
    base_url: str
    username: str | None = None
    password: str | None = None
    interval: int = 60
    port: int = 8000
    host: str = "0.0.0.0"
    docsis_path: str = DEFAULT_DOCSIS_PATH
    snapshot_dir: Path = Path("snapshots")
    sqlite_path: Path | None = Path("metrics.sqlite3")
    request_timeout: float = 10.0
    verify_tls: bool = True

    @classmethod
    def from_file(cls, path: str | Path) -> "Config":
        with Path(path).open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
        if not isinstance(raw, dict):
            raise ValueError("configuration must be a YAML mapping")
        return cls.from_mapping(raw)

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> "Config":
        base_url = str(raw.get("base_url", "")).strip()
        if not base_url:
            raise ValueError("config value 'base_url' is required")

        sqlite_path = raw.get("sqlite_path", "metrics.sqlite3")
        if sqlite_path in ("", None, False):
            db_path = None
        else:
            db_path = Path(str(sqlite_path))

        return cls(
            base_url=base_url.rstrip("/") + "/",
            username=_optional_str(raw.get("username")),
            password=_optional_str(raw.get("password")),
            interval=int(raw.get("interval", 60)),
            port=int(raw.get("port", 8000)),
            host=str(raw.get("host", "0.0.0.0")),
            docsis_path=str(raw.get("docsis_path", DEFAULT_DOCSIS_PATH)),
            snapshot_dir=Path(str(raw.get("snapshot_dir", "snapshots"))),
            sqlite_path=db_path,
            request_timeout=float(raw.get("request_timeout", 10.0)),
            verify_tls=bool(raw.get("verify_tls", True)),
        )


def _optional_str(value: Any) -> str | None:
    if value in ("", None, False):
        return None
    return str(value)
