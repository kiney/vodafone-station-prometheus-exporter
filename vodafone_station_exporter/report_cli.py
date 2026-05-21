from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .health_report import analyze_sqlite, render_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Report DOCSIS health from a Vodafone Station SQLite log")
    parser.add_argument(
        "database",
        nargs="?",
        default="metrics.sqlite3",
        help="SQLite metrics database path (default: ./metrics.sqlite3)",
    )
    parser.add_argument("--hours", type=float, help="only analyze the last N hours in the database")
    args = parser.parse_args()

    path = Path(args.database)
    try:
        report = analyze_sqlite(path, hours=args.hours)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    print(render_report(report, path), end="")
    raise SystemExit(1 if report.status == "CRITICAL" else 0)


if __name__ == "__main__":
    main()
