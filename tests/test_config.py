from __future__ import annotations

import unittest

from vodafone_station_exporter.config import Config


class ConfigTest(unittest.TestCase):
    def test_default_port_is_8018(self) -> None:
        config = Config.from_mapping({"base_url": "http://192.168.0.1/", "password": "secret"})

        self.assertEqual(config.port, 8018)

    def test_configured_port_overrides_default(self) -> None:
        config = Config.from_mapping({"base_url": "http://192.168.0.1/", "password": "secret", "port": 9000})

        self.assertEqual(config.port, 9000)


if __name__ == "__main__":
    unittest.main()
