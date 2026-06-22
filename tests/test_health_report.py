from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

from vodafone_station_exporter.docsis import DocsisStatus, DownstreamChannel, UpstreamChannel
from vodafone_station_exporter.health_report import analyze_sqlite, render_report
from vodafone_station_exporter.storage import SqliteLog


class HealthReportTest(unittest.TestCase):
    def test_healthy_database_reports_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "metrics.sqlite3"
            log = SqliteLog(db_path)
            start = datetime.fromisoformat("2026-05-21T18:00:00+02:00")
            for index in range(3):
                log.record(start + timedelta(minutes=index), _status(), None)

            report = analyze_sqlite(db_path)
            rendered = render_report(report, db_path)

        self.assertEqual(report.status, "OK")
        self.assertEqual(report.scrape_count, 3)
        self.assertIn("Status: OK", rendered)
        self.assertIn("Findings: no notable anomalies.", rendered)

    def test_anomalies_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "metrics.sqlite3"
            log = SqliteLog(db_path)
            start = datetime.fromisoformat("2026-05-21T18:00:00+02:00")
            log.record(start, _status(upstream_modulation="64-qam", upstream_power=49.0), None)
            log.record(start + timedelta(minutes=1), None, "router did not return DOCSIS status")
            log.record(
                start + timedelta(minutes=2),
                _status(locked=False, snr=0.0, upstream_modulation="16-qam", upstream_power=52.0),
                None,
            )

            report = analyze_sqlite(db_path)
            rendered = render_report(report, db_path)

        self.assertEqual(report.status, "CRITICAL")
        self.assertIn("high scrape failure rate", rendered)
        self.assertIn("downstream lock lost", rendered)
        self.assertIn("implausibly low downstream SNR", rendered)
        self.assertIn("high upstream transmit power", rendered)
        self.assertIn("degraded upstream modulation", rendered)
        self.assertIn("modulation changed", rendered)

    def test_degraded_upstream_modulation_without_change_is_warned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "metrics.sqlite3"
            log = SqliteLog(db_path)
            start = datetime.fromisoformat("2026-05-25T16:47:00+02:00")
            log.record(start, _status(upstream_modulation="16-qam", upstream_power=49.0), None)
            log.record(start + timedelta(hours=1), _status(upstream_modulation="16-qam", upstream_power=49.0), None)

            report = analyze_sqlite(db_path, hours=6)
            rendered = render_report(report, db_path)

        self.assertEqual(report.status, "WARN")
        self.assertIn("degraded upstream modulation on channel(s): 5 (16-qam)", rendered)

    def test_cli_prints_report_for_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "metrics.sqlite3"
            SqliteLog(db_path).record(datetime.fromisoformat("2026-05-21T18:00:00+02:00"), _status(), None)

            result = subprocess.run(
                [sys.executable, "-m", "vodafone_station_exporter.report_cli", str(db_path)],
                check=True,
                env=_test_env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

        self.assertIn("DOCSIS health report", result.stdout)
        self.assertIn("Status: OK", result.stdout)


def _status(
    *,
    locked: bool = True,
    snr: float = 40.0,
    upstream_modulation: str = "64-qam",
    upstream_power: float = 45.0,
) -> DocsisStatus:
    return DocsisStatus(
        downstream=[
            DownstreamChannel(
                channel_id="1",
                channel_type="SC-QAM",
                frequency_mhz="570 MHz",
                modulation="256-QAM",
                power_dbmv=9.0,
                power_dbuv=69.0,
                snr_db=snr,
                locked=locked,
                lock_status="Locked" if locked else "Unlocked",
            )
        ],
        upstream=[
            UpstreamChannel(
                channel_id="5",
                channel_type="SC-QAM",
                frequency_mhz="51.0 MHz",
                modulation=upstream_modulation,
                power_dbmv=upstream_power,
                power_dbuv=upstream_power + 60,
                ranging_success=True,
                ranging_status="Completed",
            )
        ],
    )


def _test_env() -> dict[str, str]:
    env = dict(os.environ)
    repo_root = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = str(repo_root)
    return env


if __name__ == "__main__":
    unittest.main()
