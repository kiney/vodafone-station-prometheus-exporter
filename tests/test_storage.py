from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from vodafone_station_exporter.docsis import parse_docsis_json, parse_docsis_status
from vodafone_station_exporter.storage import render_snapshot, write_snapshot


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


if __name__ == "__main__":
    unittest.main()
