from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from vodafone_station_exporter.docsis import parse_docsis_json, parse_docsis_status
from vodafone_station_exporter.storage import SqliteLog, render_snapshot, write_snapshot


class StorageTest(unittest.TestCase):
    def test_render_snapshot_uses_legacy_text_shape(self) -> None:
        status = parse_docsis_json(
            {
                "data": {
                    "ofdm_downstream": [
                        {
                            "channelid_ofdm": "33",
                            "start_frequency": "135.000000 MHz",
                            "end_frequency": "324.950012 MHz",
                            "power_ofdm": "3.6 dBmV",
                            "SNR_ofdm": "33.81 dB",
                            "FFT_ofdm": "256-qam/1024-qam/4096-qam",
                            "locked_ofdm": "Locked",
                            "ChannelType": "OFDM",
                        }
                    ],
                    "upstream": [
                        {
                            "channelidup": "5",
                            "CentralFrequency": "51.0 MHz",
                            "power": "45.0 dBmV",
                            "FFT": "64-qam",
                            "ChannelType": "SC-QAM",
                            "RangingStatus": "Completed",
                        }
                    ],
                }
            }
        )

        snapshot = render_snapshot(status)
        reparsed = parse_docsis_status(snapshot)

        self.assertTrue(snapshot.startswith("DOCSIS Status\n"))
        self.assertIn("Downstream-Kanäle", snapshot)
        self.assertIn("Upstream-Kanäle", snapshot)
        self.assertIn("3.6/63.6", snapshot)
        self.assertIn("Erfolgreich", snapshot)
        self.assertEqual(len(reparsed.downstream), 1)
        self.assertEqual(len(reparsed.upstream), 1)
        self.assertEqual(reparsed.downstream[0].channel_id, "33")

    def test_write_snapshot_uses_docsis_timestamp_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from datetime import datetime

            path = write_snapshot(Path(tmp), datetime.fromisoformat("2026-05-21T18:23:51+02:00"), "DOCSIS Status\n")

            self.assertEqual(path.name, "DOCSIS_2026-05-21T18:23:51+02:00")
            self.assertEqual(path.read_text(encoding="utf-8"), "DOCSIS Status\n")

    def test_sqlite_log_normalizes_channels(self) -> None:
        from datetime import datetime

        status = parse_docsis_json(
            {
                "data": {
                    "downstream": [
                        {
                            "channelid": "11",
                            "CentralFrequency": "642 MHz",
                            "power": "11.0 dBmV",
                            "SNR": "41.1 dB",
                            "FFT": "256-QAM",
                            "locked": "Locked",
                            "ChannelType": "SC-QAM",
                        }
                    ],
                    "upstream": [
                        {
                            "channelidup": "5",
                            "CentralFrequency": "51.0 MHz",
                            "power": "45.0 dBmV",
                            "FFT": "64-qam",
                            "ChannelType": "SC-QAM",
                            "RangingStatus": "Completed",
                        }
                    ],
                }
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "metrics.sqlite3"
            SqliteLog(db_path).record(datetime.fromisoformat("2026-05-21T18:23:51+02:00"), status, None)

            with sqlite3.connect(db_path) as conn:
                scrape = conn.execute(
                    "SELECT success, downstream_count, upstream_count FROM scrapes"
                ).fetchone()
                downstream = conn.execute(
                    """
                    SELECT d.channel_id, d.snr_db, d.power_dbuv
                    FROM downstream_channels d
                    JOIN scrapes s ON s.id = d.scrape_id
                    WHERE d.channel_id = ?
                    """,
                    ("11",),
                ).fetchone()
                upstream = conn.execute(
                    """
                    SELECT u.channel_id, u.ranging_success
                    FROM upstream_channels u
                    JOIN scrapes s ON s.id = u.scrape_id
                    WHERE u.channel_id = ?
                    """,
                    ("5",),
                ).fetchone()

            self.assertEqual(scrape, (1, 1, 1))
            self.assertEqual(downstream, ("11", 41.1, 71.0))
            self.assertEqual(upstream, ("5", 1))

    def test_sqlite_log_records_failed_scrape_without_channels(self) -> None:
        from datetime import datetime

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "metrics.sqlite3"
            SqliteLog(db_path).record(datetime.fromisoformat("2026-05-21T18:23:51+02:00"), None, "boom")

            with sqlite3.connect(db_path) as conn:
                scrape = conn.execute("SELECT success, error FROM scrapes").fetchone()
                downstream_count = conn.execute("SELECT COUNT(*) FROM downstream_channels").fetchone()[0]
                upstream_count = conn.execute("SELECT COUNT(*) FROM upstream_channels").fetchone()[0]

            self.assertEqual(scrape, (0, "boom"))
            self.assertEqual(downstream_count, 0)
            self.assertEqual(upstream_count, 0)


if __name__ == "__main__":
    unittest.main()
