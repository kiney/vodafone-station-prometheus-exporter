from __future__ import annotations

from collections.abc import Iterable
import json
import re
from urllib.parse import urljoin

import requests

from .config import Config
from .scraper import RouterScraper


DISCOVERY_PATHS = (
    "/",
    "/index.html",
    "/login.html",
    "/api/v1/session",
    "/api/v1/session/login",
    "/api/v1/sta_docsis_status",
    "/php/status_docsis_data.php",
    "/status_docsis_data.php",
    "/docsis.html",
    "/status_docsis.html",
)


def discover_router(config: Config) -> list[str]:
    session = requests.Session()
    lines: list[str] = []
    lines.append("Discovery without login")
    lines.extend(_probe_paths(session, config, DISCOVERY_PATHS))
    lines.append("Login page structure")
    lines.extend(_login_page_structure(session, config))

    if config.password:
        lines.append("Login probes")
        for result in _login_attempts(session, config):
            lines.append(result)
        lines.append("Discovery after login probes")
        lines.extend(_probe_paths(session, config, DISCOVERY_PATHS))
    return lines


def save_login_page(config: Config, destination: str) -> str:
    session = requests.Session()
    response = session.get(config.base_url, timeout=config.request_timeout, verify=config.verify_tls)
    response.raise_for_status()
    with open(destination, "w", encoding="utf-8") as handle:
        handle.write(response.text)
    return destination


def save_docsis_api(config: Config, destination: str) -> str:
    scraper = RouterScraper(config)
    scraper._login()
    response = scraper.session.get(
        urljoin(config.base_url, "api/v1/sta_docsis_status"),
        timeout=config.request_timeout,
        verify=config.verify_tls,
    )
    response.raise_for_status()
    with open(destination, "w", encoding="utf-8") as handle:
        handle.write(response.text)
    return destination


def debug_login(config: Config) -> list[str]:
    scraper = RouterScraper(config)
    lines: list[str] = []
    username = config.username or "admin"
    first = scraper._post_login({"username": username, "password": "seeksalthash", "logout": ""})
    lines.append("first=" + _redact_login_json(first))
    lines.append("cookies_after_first=" + ",".join(cookie.name for cookie in scraper.session.cookies))
    salt = first.get("salt")
    salt_webui = first.get("saltwebui")
    if isinstance(salt, str) and isinstance(salt_webui, str) and config.password:
        from .scraper import _pbkdf2_hex

        hashed = _pbkdf2_hex(config.password, salt)
        password = _pbkdf2_hex(hashed, salt_webui)
    else:
        password = config.password or ""
    second = scraper._post_login({"username": username, "password": password})
    lines.append("second=" + _redact_login_json(second))
    lines.append("cookies_after_second=" + ",".join(cookie.name for cookie in scraper.session.cookies))
    first_takeover = scraper._post_login({"username": username, "password": "seeksalthash", "logout": "true"})
    lines.append("first_takeover=" + _redact_login_json(first_takeover))
    salt = first_takeover.get("salt")
    salt_webui = first_takeover.get("saltwebui")
    if isinstance(salt, str) and isinstance(salt_webui, str) and config.password:
        from .scraper import _pbkdf2_hex

        hashed = _pbkdf2_hex(config.password, salt)
        password = _pbkdf2_hex(hashed, salt_webui)
    takeover_second = scraper._post_login({"username": username, "password": password})
    lines.append("second_takeover=" + _redact_login_json(takeover_second))
    lines.append(
        "cookies_after_takeover="
        + ",".join(f"{cookie.name}:domain={cookie.domain}:path={cookie.path}" for cookie in scraper.session.cookies)
    )
    for path in ("/api/session/menu", "/api/session/init_page", "/api/sta_docsis_status", "/api/v1/session/menu", "/api/v1/session/init_page", "/api/v1/sta_docsis_status"):
        response = scraper.session.get(
            urljoin(config.base_url, path.lstrip("/")),
            timeout=config.request_timeout,
            verify=config.verify_tls,
        )
        lines.append(_summarize_response(path, response, include_json_values=True))
    lines.append("full_login_retry")
    scraper = RouterScraper(config)
    try:
        scraper._login()
        lines.append("full_login=ok")
    except Exception as exc:
        lines.append(f"full_login=ERROR {type(exc).__name__}: {exc}")
    lines.append("cookies_after_full_login=" + ",".join(cookie.name for cookie in scraper.session.cookies))
    for path in ("/api/session/menu", "/api/session/init_page", "/api/sta_docsis_status", "/api/v1/session/menu", "/api/v1/session/init_page", "/api/v1/sta_docsis_status"):
        response = scraper.session.get(
            urljoin(config.base_url, path.lstrip("/")),
            timeout=config.request_timeout,
            verify=config.verify_tls,
        )
        lines.append(_summarize_response(path, response, include_json_values=True))
    return lines


def _redact_login_json(data: dict[str, object]) -> str:
    redacted = dict(data)
    for key in ("salt", "saltwebui", "token"):
        if key in redacted:
            redacted[key] = "<present>"
    return json.dumps(redacted, ensure_ascii=False)[:600]


def _login_page_structure(session: requests.Session, config: Config) -> list[str]:
    url = urljoin(config.base_url, "/")
    response = session.get(url, timeout=config.request_timeout, verify=config.verify_tls)
    body = response.text
    lines: list[str] = []
    inputs = sorted(set(re.findall(r"<input[^>]+(?:name|id)=[\"']([^\"']+)", body, re.IGNORECASE)))
    scripts = sorted(set(re.findall(r"<script[^>]+src=[\"']([^\"']+)", body, re.IGNORECASE)))
    api_paths = sorted(set(re.findall(r"['\"](/api/v1/[^'\"]+)", body)))
    lines.append("inputs=" + ",".join(inputs[:30]))
    lines.append("scripts=" + ",".join(scripts[:30]))
    lines.append("api_paths=" + ",".join(api_paths[:50]))
    for script in scripts[:10]:
        if script.startswith(("http://", "https://")):
            script_url = script
        else:
            script_url = urljoin(config.base_url, script.lstrip("/"))
        try:
            script_response = session.get(script_url, timeout=config.request_timeout, verify=config.verify_tls)
        except Exception as exc:
            lines.append(f"script {script}: ERROR {type(exc).__name__}: {exc}")
            continue
        script_api_paths = sorted(set(re.findall(r"['\"](/api/v1/[^'\"]+)", script_response.text)))
        interesting = sorted(set(re.findall(r"(?:login|password|session|csrf|token|nonce|salt|auth)[A-Za-z0-9_/-]{0,60}", script_response.text, re.IGNORECASE)))
        lines.append(f"script {script}: len={len(script_response.text)} api_paths={','.join(script_api_paths[:30])} words={','.join(interesting[:40])}")
    return lines


def _probe_paths(session: requests.Session, config: Config, paths: Iterable[str]) -> list[str]:
    lines: list[str] = []
    for path in paths:
        url = urljoin(config.base_url, path.lstrip("/"))
        try:
            response = session.get(url, timeout=config.request_timeout, verify=config.verify_tls)
            lines.append(_summarize_response(path, response))
        except Exception as exc:
            lines.append(f"{path}: ERROR {type(exc).__name__}: {exc}")
    return lines


def _login_attempts(session: requests.Session, config: Config) -> list[str]:
    attempts = [
        ("POST", "/api/v1/session", {"password": config.password}),
        ("POST", "/api/v1/session", {"username": config.username or "admin", "password": config.password}),
        ("POST", "/api/v1/session/login", {"password": config.password}),
        ("POST", "/api/v1/session/login", {"username": config.username or "admin", "password": config.password}),
        ("POST", "/login", {"username": config.username or "admin", "password": config.password}),
        ("POST", "/login.cgi", {"username": config.username or "admin", "password": config.password}),
        ("POST", "/php/login.php", {"username": config.username or "admin", "password": config.password}),
    ]
    lines: list[str] = []
    for method, path, data in attempts:
        url = urljoin(config.base_url, path.lstrip("/"))
        try:
            response = session.request(
                method,
                url,
                json=data if path.startswith("/api/") else None,
                data=data if not path.startswith("/api/") else None,
                timeout=config.request_timeout,
                verify=config.verify_tls,
            )
            lines.append(_summarize_response(path, response, include_json_values=True))
        except Exception as exc:
            lines.append(f"{path}: ERROR {type(exc).__name__}: {exc}")
    return lines


def _summarize_response(path: str, response: requests.Response, include_json_values: bool = False) -> str:
    body = response.text or ""
    markers = []
    lowered = body.casefold()
    for marker in ("docsis", "downstream", "upstream", "login", "password", "csrf", "token", "session"):
        if marker in lowered:
            markers.append(marker)
    detail = (_json_summary(body) if include_json_values else _json_keys(body)) or _title(body) or _snippet(body)
    return (
        f"{path}: HTTP {response.status_code} len={len(body)} "
        f"type={response.headers.get('content-type', '?')} markers={','.join(markers) or '-'} detail={detail}"
    )


def _json_keys(body: str) -> str | None:
    try:
        parsed = json.loads(body)
    except ValueError:
        return None
    if isinstance(parsed, dict):
        return "json_keys=" + ",".join(str(key) for key in list(parsed.keys())[:12])
    if isinstance(parsed, list):
        return f"json_list_len={len(parsed)}"
    return f"json_{type(parsed).__name__}"


def _json_summary(body: str) -> str | None:
    try:
        parsed = json.loads(body)
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return _json_keys(body)
    scrubbed = {}
    for key, value in parsed.items():
        key_text = str(key)
        if key_text.lower() in {"password", "token", "session", "sessionid", "auth", "authorization"}:
            scrubbed[key_text] = "<redacted>"
        else:
            scrubbed[key_text] = value
    return "json=" + json.dumps(scrubbed, ensure_ascii=False)[:400]


def _title(body: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return "title=" + re.sub(r"\s+", " ", match.group(1)).strip()[:120]


def _snippet(body: str) -> str:
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)).strip()
    return "snippet=" + text[:120]
