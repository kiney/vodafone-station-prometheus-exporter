from pathlib import Path
import unittest

from vodafone_station_exporter.docsis import parse_docsis_status
from vodafone_station_exporter.docsis import parse_docsis_json
from vodafone_station_exporter.metrics import render_metrics


class DocsisParserTest(unittest.TestCase):
    def test_parse_snapshot_counts_and_values(self) -> None:
        raw = Path("snapshots/DOCSIS_2026-05-21T16:41:54+02:00").read_text(encoding="utf-8")

        status = parse_docsis_status(raw)

        self.assertEqual(len(status.downstream), 33)
        self.assertEqual(len(status.upstream), 5)
        self.assertEqual(status.downstream[0].channel_id, "33")
        self.assertEqual(status.downstream[0].power_dbmv, 3.8)
        self.assertEqual(status.downstream[0].power_dbuv, 63.8)
        self.assertEqual(status.downstream[0].snr_db, 34.33)
        self.assertIs(status.downstream[0].locked, True)
        self.assertEqual(status.upstream[0].channel_id, "10")
        self.assertIs(status.upstream[0].ranging_success, True)

    def test_render_metrics_contains_expected_samples(self) -> None:
        raw = Path("snapshots/DOCSIS_2026-05-21T16:41:54+02:00").read_text(encoding="utf-8")
        status = parse_docsis_status(raw)

        metrics = render_metrics(status, None, None)

        self.assertIn("vodafone_station_scrape_success 1", metrics)
        self.assertIn('vodafone_station_docsis_channels{direction="downstream"} 33', metrics)
        self.assertIn('vodafone_station_docsis_downstream_snr_db{channel_id="33"', metrics)
        self.assertIn('vodafone_station_docsis_upstream_ranging_success{channel_id="10"', metrics)

    def test_parse_html_table_rows(self) -> None:
        raw = """
        <h1>DOCSIS Status</h1>
        <h2>Downstream-Kanäle</h2>
        <table><tr><th>Kanal ID</th><th>Kanaltyp</th><th>Frequenz (MHz)</th><th>Modulation</th><th>Empf. Signalstärke (dBmV/dBµV)</th><th>SNR/MER (dB)</th><th>Lock Status</th></tr>
        <tr><td>33</td><td>OFDM</td><td>135~325.0</td><td>256-qam</td><td>3.8/63.8</td><td>34.33</td><td>JA</td></tr></table>
        <h2>Upstream-Kanäle</h2>
        <table><tr><th>Kanal ID</th><th>Kanaltyp</th><th>Frequenz (MHz)</th><th>Modulation</th><th>Send. Signalstärke (dBmV/dBµV)</th><th>Ranging Status</th></tr>
        <tr><td>10</td><td>OFDMA</td><td>29.8~</td><td>16-qam</td><td>41.3/101.3</td><td>Erfolgreich</td></tr></table>
        """

        status = parse_docsis_status(raw)

        self.assertEqual(len(status.downstream), 1)
        self.assertEqual(len(status.upstream), 1)
        self.assertEqual(status.downstream[0].snr_db, 34.33)
        self.assertIs(status.upstream[0].ranging_success, True)

    def test_parse_real_api_shape(self) -> None:
        status = parse_docsis_json(
            {
                "error": "ok",
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
                    "ofdma_upstream": [
                        {
                            "channelidup": "10",
                            "start_frequency": "29.800000 MHz",
                            "power": "43.3 dBmV",
                            "FFT": "16-qam",
                            "ChannelType": "OFDMA",
                            "RangingStatus": "Completed",
                        }
                    ],
                },
            }
        )

        self.assertEqual(len(status.downstream), 2)
        self.assertEqual(status.downstream[0].channel_id, "33")
        self.assertEqual(status.downstream[0].frequency_mhz, "135~324.95")
        self.assertEqual(status.downstream[0].power_dbuv, 63.6)
        self.assertEqual(status.downstream[1].modulation, "256-QAM")
        self.assertEqual(len(status.upstream), 1)
        self.assertEqual(status.upstream[0].channel_id, "10")
        self.assertIs(status.upstream[0].ranging_success, True)


if __name__ == "__main__":
    unittest.main()
