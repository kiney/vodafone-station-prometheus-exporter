from __future__ import annotations

import json
import hashlib
import unittest

from cryptography.hazmat.primitives.ciphers.aead import AESCCM

from vodafone_station_exporter.config import Config
from vodafone_station_exporter.scraper import RouterScraper


class RouterScraperTest(unittest.TestCase):
    def test_expired_session_logs_in_again_before_retrying_docsis_api(self) -> None:
        scraper = RouterScraper(
            Config.from_mapping(
                {
                    "base_url": "http://router.test/",
                    "password": "secret",
                }
            )
        )
        session = FakeSession(
            gets=[
                FakeResponse("<form><input type='password'><button>Login</button></form>", content_type="text/html"),
                FakeResponse({}, content_type="application/json"),
                FakeResponse({"token": "csrf"}, content_type="application/json"),
                FakeResponse(_docsis_payload(), content_type="application/json"),
            ],
            posts=[
                FakeResponse({"error": "ok", "salt": "none"}, content_type="application/json"),
                FakeResponse({"error": "ok"}, content_type="application/json"),
            ],
        )
        scraper.session = session
        scraper._logged_in = True

        result = scraper.fetch_docsis()

        self.assertEqual(result.url, "http://router.test/api/v1/sta_docsis_status")
        self.assertIn('"channelid": "11"', result.body)
        self.assertEqual(
            session.get_urls,
            [
                "http://router.test/api/v1/sta_docsis_status",
                "http://router.test/api/v1/session/menu",
                "http://router.test/api/v1/session/init_page",
                "http://router.test/api/v1/sta_docsis_status",
            ],
        )
        self.assertEqual(len(session.post_urls), 2)

    def test_login_page_without_password_fails_on_configured_path(self) -> None:
        scraper = RouterScraper(
            Config.from_mapping(
                {
                    "base_url": "http://router.test/",
                }
            )
        )
        session = FakeSession(
            gets=[
                FakeResponse("<form><input type='password'><button>Anmelden</button></form>", content_type="text/html"),
            ],
            posts=[],
        )
        scraper.session = session

        with self.assertRaisesRegex(RuntimeError, "requires login"):
            scraper.fetch_docsis()

        self.assertEqual(session.get_urls, ["http://router.test/api/v1/sta_docsis_status"])
        self.assertEqual(session.post_urls, [])

    def test_custom_docsis_path_is_the_only_scraped_path(self) -> None:
        scraper = RouterScraper(
            Config.from_mapping(
                {
                    "base_url": "http://router.test/",
                    "password": "secret",
                    "docsis_path": "/custom-docsis",
                }
            )
        )
        session = FakeSession(
            gets=[
                FakeResponse("not docsis", content_type="text/plain"),
            ],
            posts=[],
        )
        scraper.session = session

        with self.assertRaisesRegex(RuntimeError, "/custom-docsis did not contain DOCSIS status"):
            scraper.fetch_docsis()

        self.assertEqual(session.get_urls, ["http://router.test/custom-docsis"])
        self.assertEqual(session.post_urls, [])

    def test_default_api_404_falls_back_to_tg_login_and_docsis_page(self) -> None:
        password = "secret"
        salt = "0011223344556677"
        iv = "8899aabbccddeeff"
        session_id = "0123456789abcdef"
        key = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt), 1000, dklen=16
        )
        encrypted_nonce = AESCCM(key).encrypt(
            bytes.fromhex(iv), b"csrf-value", b"nonce"
        ).hex()
        login_page = f"""
            <script>
            var currentSessionId = '{session_id}';
            var myIv = '{iv}';
            var mySalt = '{salt}';
            var loginUserName = 'admin';
            </script>
        """
        docsis_page = """
            var json_dsData = [{"ChannelID":"11","ChannelType":"SC-QAM","Frequency":"642 MHz","Modulation":"256-QAM","PowerLevel":"11.0 dBmV/71.0 dBµV","SNRLevel":"41.1 dB","LockStatus":"Locked"}];
            var json_usData = [{"ChannelID":"8","ChannelType":"ATDMA","Frequency":"45 MHz","Modulation":"64-QAM","PowerLevel":"43.5 dBmV/103.5 dBµV","LockStatus":"ACTIVE"}];
        """
        scraper = RouterScraper(
            Config.from_mapping(
                {"base_url": "http://router.test/", "password": password}
            )
        )
        session = FakeSession(
            gets=[
                FakeResponse("not found", status_code=404, content_type="text/html"),
                FakeResponse(login_page, content_type="text/html"),
                FakeResponse(docsis_page, content_type="text/html"),
                FakeResponse(docsis_page, content_type="text/html"),
            ],
            posts=[
                FakeResponse(
                    {"p_status": "AdminMatch", "encryptData": encrypted_nonce},
                    content_type="application/json",
                ),
                FakeResponse({"LoginStatus": "yes"}, content_type="application/json"),
            ],
        )
        scraper.session = session

        result = scraper.fetch_docsis()
        second_result = scraper.fetch_docsis()

        self.assertEqual(result.url, "http://router.test/php/status_docsis_data.php")
        self.assertEqual(second_result.url, result.url)
        payload = json.loads(result.body)
        self.assertEqual(payload["data"]["downstream"][0]["ChannelID"], "11")
        self.assertEqual(
            session.get_urls,
            [
                "http://router.test/api/v1/sta_docsis_status",
                "http://router.test/",
                "http://router.test/php/status_docsis_data.php",
                "http://router.test/php/status_docsis_data.php",
            ],
        )
        self.assertEqual(
            session.post_urls,
            [
                "http://router.test/php/ajaxSet_Password.php",
                "http://router.test/php/ajaxSet_Session.php",
            ],
        )
        self.assertEqual(session.headers["csrfNonce"], "csrf-value")


class FakeSession:
    def __init__(self, gets: list[FakeResponse], posts: list[FakeResponse]) -> None:
        self.gets = gets
        self.posts = posts
        self.get_urls: list[str] = []
        self.post_urls: list[str] = []
        self.headers: dict[str, str] = {}
        self.params: dict[str, str] = {}

    def get(self, url: str, **kwargs: object) -> "FakeResponse":
        self.get_urls.append(url)
        return self.gets.pop(0)

    def post(self, url: str, **kwargs: object) -> "FakeResponse":
        self.post_urls.append(url)
        return self.posts.pop(0)

    def close(self) -> None:
        pass


class FakeResponse:
    def __init__(self, payload: object, status_code: int = 200, content_type: str = "text/plain") -> None:
        self.payload = payload
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self.text = payload if isinstance(payload, str) else json.dumps(payload)

    def json(self) -> object:
        if isinstance(self.payload, str):
            raise ValueError("not json")
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _docsis_payload() -> dict[str, object]:
    return {
        "error": "ok",
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
        },
    }


if __name__ == "__main__":
    unittest.main()
