from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import random
import re
from urllib.parse import urljoin

from cryptography.hazmat.primitives.ciphers.aead import AESCCM
import requests

from .config import Config, DEFAULT_DOCSIS_PATH
from .docsis import parse_docsis_json


@dataclass(frozen=True)
class ScrapeResult:
    url: str
    body: str


class RouterScraper:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.session = self._new_session()
        self._logged_in = False
        self._csrf_token = ""
        self._router_kind: str | None = None

    def fetch_docsis(self) -> ScrapeResult:
        if self._router_kind == "tg":
            return self._fetch_tg_with_login_retry()

        last_error: Exception | None = None
        for login_mode in ("current", "login", "fresh_login"):
            try:
                if login_mode == "login":
                    self._login()
                elif login_mode == "fresh_login":
                    self._reset_session()
                    self._login()
            except Exception as exc:
                last_error = exc
                if login_mode == "login" and self.config.password:
                    continue
                raise RuntimeError(f"could not fetch DOCSIS status: {exc}") from exc

            try:
                return self._fetch_docsis()
            except _CgaApiNotFound:
                self._router_kind = "tg"
                return self._fetch_tg_with_login_retry()
            except _LoginRequired as exc:
                last_error = exc
                self._logged_in = False
                if not self.config.password:
                    break
            except Exception as exc:  # requests exposes several subclasses here.
                raise RuntimeError(f"could not fetch DOCSIS status: {exc}") from exc
        raise RuntimeError(f"could not fetch DOCSIS status: {last_error}") from last_error

    def _fetch_tg_with_login_retry(self) -> ScrapeResult:
        last_error: Exception | None = None
        for fresh in (False, True):
            try:
                if fresh:
                    self._reset_session()
                if not self._logged_in:
                    self._login_tg()
                return self._fetch_tg_docsis()
            except _LoginRequired as exc:
                last_error = exc
                self._logged_in = False
            except Exception as exc:
                raise RuntimeError(f"could not fetch DOCSIS status: {exc}") from exc
        raise RuntimeError(f"could not fetch DOCSIS status: {last_error}") from last_error

    def _new_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update(
            {
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Referer": self.config.base_url,
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
                ),
                "X-Requested-With": "XMLHttpRequest",
            }
        )
        return session

    def _reset_session(self) -> None:
        self.session.close()
        self.session = self._new_session()
        self._logged_in = False
        self._csrf_token = ""

    def _fetch_docsis(self) -> ScrapeResult:
        url = urljoin(self.config.base_url, self.config.docsis_path.lstrip("/"))
        response = self.session.get(
            url,
            timeout=self.config.request_timeout,
            verify=self.config.verify_tls,
        )
        if _looks_like_login_required(response):
            raise _LoginRequired(f"{url} requires login")
        if response.status_code == 404 and self.config.docsis_path == DEFAULT_DOCSIS_PATH:
            raise _CgaApiNotFound(url)
        response.raise_for_status()
        parsed = _try_parse_docsis_api(response)
        if parsed:
            return ScrapeResult(url=url, body=parsed)
        if _has_docsis_content(response.text):
            return ScrapeResult(url=url, body=response.text)
        raise ValueError(
            f"{url} did not contain DOCSIS status "
            f"(status={response.status_code}, content_type={response.headers.get('content-type', '')!r})"
        )

    def _login(self, logout_other_session: bool = False) -> None:
        if self._logged_in:
            return
        if not self.config.password:
            raise RuntimeError("router login required but no password is configured")
        username = self.config.username or "admin"
        first = self._post_login(
            {
                "username": username,
                "password": "seeksalthash",
                "logout": "true" if logout_other_session else "",
            }
        )
        if first.get("message") == "MSG_LOGIN_150" and not logout_other_session:
            self._login(logout_other_session=True)
            return
        if first.get("error") != "ok":
            raise RuntimeError(f"salt request failed: {first.get('message', first.get('error'))}")

        salt = first.get("salt")
        if salt == "none":
            password = self.config.password
        else:
            salt_webui = first.get("saltwebui")
            if not isinstance(salt, str) or not isinstance(salt_webui, str):
                raise RuntimeError("router login response did not contain salts")
            hashed = _pbkdf2_hex(self.config.password, salt)
            password = _pbkdf2_hex(hashed, salt_webui)

        second = self._post_login({"username": username, "password": password})
        if second.get("message") == "MSG_LOGIN_150" and not logout_other_session:
            self._logged_in = False
            self._login(logout_other_session=True)
            return
        if second.get("error") != "ok":
            data = second.get("data") if isinstance(second.get("data"), dict) else {}
            suffix = f" failedAttempts={data.get('failedAttempts')}" if data else ""
            raise RuntimeError(f"login failed: {second.get('message', second.get('error'))}{suffix}")
        self._logged_in = True
        self._router_kind = "cga"
        self._prime_session()

    def _login_tg(self) -> None:
        if not self.config.password:
            raise RuntimeError("router login required but no password is configured")

        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "csrfNonce": "undefined",
                "Origin": self.config.base_url.rstrip("/"),
                "Referer": self.config.base_url,
            }
        )
        self.session.params = {"_n": str(random.randint(10000, 99999))}
        response = self.session.get(
            self.config.base_url,
            timeout=self.config.request_timeout,
            verify=self.config.verify_tls,
        )
        response.raise_for_status()

        session_id = _javascript_string(response.text, "currentSessionId")
        iv = bytes.fromhex(_javascript_string(response.text, "myIv"))
        salt = bytes.fromhex(_javascript_string(response.text, "mySalt"))
        username = self.config.username or _javascript_string(response.text, "loginUserName")
        key = hashlib.pbkdf2_hmac(
            "sha256", self.config.password.encode(), salt, 1000, dklen=16
        )
        plaintext = json.dumps(
            {"Password": self.config.password, "Nonce": session_id},
            separators=(", ", ": "),
        ).encode()
        encrypted = AESCCM(key, tag_length=16).encrypt(
            iv, plaintext, b"loginPassword"
        )
        login_response = self.session.post(
            urljoin(self.config.base_url, "php/ajaxSet_Password.php"),
            json={
                "AuthData": "loginPassword",
                "EncryptData": encrypted.hex(),
                "Name": username,
            },
            timeout=self.config.request_timeout,
            verify=self.config.verify_tls,
        )
        login_response.raise_for_status()
        payload = login_response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("TG router login returned non-object JSON")
        status = str(payload.get("p_status", ""))
        if "Match" not in status and status != "Default":
            raise RuntimeError(f"TG router login failed: {status or 'unknown status'}")
        encrypted_nonce = payload.get("encryptData")
        if not isinstance(encrypted_nonce, str):
            raise RuntimeError("TG router login did not return an encrypted CSRF nonce")
        try:
            csrf_nonce = AESCCM(key, tag_length=16).decrypt(
                iv, bytes.fromhex(encrypted_nonce), b"nonce"
            ).decode()
        except (ValueError, UnicodeDecodeError) as exc:
            raise RuntimeError("could not decrypt TG router CSRF nonce") from exc
        self._csrf_token = csrf_nonce
        self.session.headers["csrfNonce"] = csrf_nonce

        activate = self.session.post(
            urljoin(self.config.base_url, "php/ajaxSet_Session.php"),
            timeout=self.config.request_timeout,
            verify=self.config.verify_tls,
        )
        if _looks_like_tg_session_loss(activate):
            raise _LoginRequired("TG router rejected the new session")
        activate.raise_for_status()
        try:
            activate_payload = activate.json()
        except ValueError:
            activate_payload = {}
        if isinstance(activate_payload, dict) and activate_payload.get("LoginStatus") == "no":
            raise _LoginRequired("TG router did not activate the new session")
        self._logged_in = True
        self._router_kind = "tg"

    def _fetch_tg_docsis(self) -> ScrapeResult:
        url = urljoin(self.config.base_url, "php/status_docsis_data.php")
        response = self.session.get(
            url,
            timeout=self.config.request_timeout,
            verify=self.config.verify_tls,
        )
        if _looks_like_tg_session_loss(response):
            raise _LoginRequired(f"{url} requires login")
        response.raise_for_status()
        payload = _parse_tg_docsis_page(response.text)
        status = parse_docsis_json(payload)
        if status.total_channels == 0:
            raise ValueError(f"{url} did not contain DOCSIS channels")
        return ScrapeResult(url=url, body=json.dumps(payload, ensure_ascii=False))

    def _post_login(self, data: dict[str, str]) -> dict[str, object]:
        response = self.session.post(
            urljoin(self.config.base_url, "api/v1/session/login"),
            data=data,
            headers={"X-CSRF-TOKEN": ""},
            timeout=self.config.request_timeout,
            verify=self.config.verify_tls,
        )
        response.raise_for_status()
        parsed = response.json()
        if not isinstance(parsed, dict):
            raise RuntimeError("router login returned non-object JSON")
        return parsed

    def _prime_session(self) -> None:
        self.session.get(
            urljoin(self.config.base_url, "api/v1/session/menu"),
            timeout=self.config.request_timeout,
            verify=self.config.verify_tls,
        ).raise_for_status()
        response = self.session.get(
            urljoin(self.config.base_url, "api/v1/session/init_page"),
            timeout=self.config.request_timeout,
            verify=self.config.verify_tls,
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError:
            return
        if isinstance(payload, dict) and isinstance(payload.get("token"), str):
            self._csrf_token = payload["token"]


def _has_docsis_content(text: str) -> bool:
    lowered = text.casefold()
    return "docsis" in lowered and ("downstream" in lowered or "downstream-kanäle" in lowered)


def _looks_like_login_required(response: requests.Response) -> bool:
    if response.status_code in {401, 403}:
        return True
    content_type = response.headers.get("content-type", "")
    if "json" in content_type.casefold():
        try:
            payload = response.json()
        except ValueError:
            return False
        if isinstance(payload, dict):
            message = str(payload.get("message", "") or payload.get("error", "")).casefold()
            return any(marker in message for marker in ("login", "auth", "session"))
        return False
    lowered = response.text.casefold()
    return (
        "<form" in lowered
        and "password" in lowered
        and ("login" in lowered or "anmelden" in lowered)
    )


def _try_parse_docsis_api(response: requests.Response) -> str | None:
    content_type = response.headers.get("content-type", "")
    if "json" not in content_type.casefold():
        return None
    payload = response.json()
    if not isinstance(payload, dict):
        return None
    status = parse_docsis_json(payload)
    if status.total_channels == 0:
        return None
    return json.dumps(payload, ensure_ascii=False)


def _pbkdf2_hex(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 1000, dklen=16).hex()


class _LoginRequired(RuntimeError):
    pass


class _CgaApiNotFound(RuntimeError):
    pass


def _javascript_string(body: str, name: str) -> str:
    match = re.search(
        rf"\b(?:var\s+)?{re.escape(name)}\s*=\s*(['\"])(.*?)\1\s*;",
        body,
    )
    if not match:
        raise RuntimeError(f"TG router login page did not contain {name}")
    return match.group(2)


def _parse_tg_docsis_page(body: str) -> dict[str, object]:
    data: dict[str, object] = {}
    for variable, key in (("json_dsData", "downstream"), ("json_usData", "upstream")):
        match = re.search(
            rf"^\s*(?:var\s+)?{variable}\s*=\s*(.*?)\s*;\s*$",
            body,
            re.MULTILINE,
        )
        if not match:
            raise ValueError(f"TG DOCSIS page did not contain {variable}")
        try:
            value = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            raise ValueError(f"TG DOCSIS page contained invalid {variable}") from exc
        if not isinstance(value, list):
            raise ValueError(f"TG DOCSIS page {variable} was not an array")
        data[key] = value
    return {"data": data}


def _looks_like_tg_session_loss(response: requests.Response) -> bool:
    if response.status_code in {401, 403}:
        return True
    if response.status_code != 400:
        return False
    lowered = response.text.casefold()
    return "session_lost" in lowered or "session lost" in lowered or "index.php" in lowered
