from __future__ import annotations

import json
import unittest
from unittest.mock import Mock, patch

from vodafone_station_exporter.app import ExporterState
from vodafone_station_exporter.config import Config
from vodafone_station_exporter.scraper import ScrapeResult


class ExporterStateTest(unittest.TestCase):
    def test_snapshots_are_only_written_when_enabled(self) -> None:
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                config = Config.from_mapping(
                    {
                        "base_url": "http://router.test/",
                        "sqlite_path": None,
                        "snapshots_enabled": enabled,
                    }
                )
                state = ExporterState(config)
                state.scraper = Mock(
                    fetch_docsis=Mock(
                        return_value=ScrapeResult(
                            url="http://router.test/docsis",
                            body=json.dumps(_docsis_payload()),
                        )
                    )
                )

                with patch("vodafone_station_exporter.app.write_snapshot") as write:
                    state.scrape()

                self.assertEqual(write.called, enabled)


def _docsis_payload() -> dict[str, object]:
    return {
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
            "upstream": [],
        }
    }


if __name__ == "__main__":
    unittest.main()
