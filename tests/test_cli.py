from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

from vodafone_station_exporter.app import _request_shutdown


class CliTest(unittest.TestCase):
    def test_help_documents_default_config_path(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "vodafone_station_exporter", "--help"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        self.assertIn("--config CONFIG", result.stdout)
        self.assertIn("default: ./config.yml", result.stdout)

    def test_once_uses_config_yml_from_cwd_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "config.yml").write_text(
                textwrap.dedent(
                    """
                    base_url: http://127.0.0.1:9/
                    username: admin
                    password: nope
                    request_timeout: 0.1
                    sqlite_path: null
                    snapshot_dir: snapshots
                    """
                ).strip(),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, "-m", "vodafone_station_exporter", "--once"],
                cwd=tmp,
                env=_test_env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )

        self.assertEqual(result.returncode, 0)
        self.assertIn("vodafone_station_scrape_success 0", result.stdout)

    def test_shutdown_handler_stops_scraper_and_server(self) -> None:
        import threading

        class FakeServer:
            def __init__(self) -> None:
                self.shutdown_called = threading.Event()

            def shutdown(self) -> None:
                self.shutdown_called.set()

        stop_event = threading.Event()
        server = FakeServer()

        thread = _request_shutdown(stop_event, server, 15)
        thread.join(timeout=2)

        self.assertTrue(stop_event.is_set())
        self.assertTrue(server.shutdown_called.is_set())


def _test_env() -> dict[str, str]:
    env = dict(os.environ)
    repo_root = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = str(repo_root)
    return env


if __name__ == "__main__":
    unittest.main()
