"""Apple Push Notification sender (token-based .p8 auth).

Idle until APNS_KEY_P8 (contents or path), APNS_KEY_ID, APNS_TEAM_ID and
APNS_BUNDLE_ID are set; APNS_USE_SANDBOX=1 targets the sandbox host.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_PROD_HOST = "https://api.push.apple.com"
_SANDBOX_HOST = "https://api.sandbox.push.apple.com"
_TOKEN_TTL_S = 50 * 60  # Apple rejects provider tokens older than 60 min.

_lock = threading.Lock()
_cached_token: Optional[str] = None
_cached_at: float = 0.0
_client = None  # lazily-built httpx.Client(http2=True)


def _key_p8() -> str:
    raw = os.getenv("APNS_KEY_P8", "").strip()
    if raw and "BEGIN PRIVATE KEY" not in raw and os.path.exists(raw):
        try:
            with open(raw, "r", encoding="utf-8") as fh:
                return fh.read()
        except OSError as exc:
            logger.error("[apns] cannot read APNS_KEY_P8 path: %s", exc)
            return ""
    # Allow literal "\n" in an env var to stand in for real newlines.
    return raw.replace("\\n", "\n")


def is_configured() -> bool:
    return bool(
        _key_p8()
        and os.getenv("APNS_KEY_ID", "").strip()
        and os.getenv("APNS_TEAM_ID", "").strip()
        and os.getenv("APNS_BUNDLE_ID", "").strip()
    )


def _provider_token() -> Optional[str]:
    global _cached_token, _cached_at
    with _lock:
        now = time.time()
        if _cached_token and (now - _cached_at) < _TOKEN_TTL_S:
            return _cached_token
        try:
            import jwt
            token = jwt.encode(
                {"iss": os.getenv("APNS_TEAM_ID", "").strip(), "iat": int(now)},
                _key_p8(),
                algorithm="ES256",
                headers={"kid": os.getenv("APNS_KEY_ID", "").strip()},
            )
            _cached_token = token
            _cached_at = now
            return token
        except Exception as exc:  # noqa: BLE001
            logger.error("[apns] provider token signing failed: %s", exc)
            return None


def _http():
    global _client
    if _client is None:
        import httpx  # http2 needs the 'h2' extra installed
        _client = httpx.Client(http2=True, timeout=10.0)
    return _client


def send(
    token: str,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
    silent: bool = False,
) -> Tuple[bool, str]:
    """Send one alert; returns (ok, status). status "gone" means prune the token. Never raises.
    `silent` (the user's quiet hours): no sound, delivered without lighting the screen."""
    aps: Dict[str, Any] = {"alert": {"title": title, "body": body}}
    if silent:
        aps["interruption-level"] = "passive"
    else:
        aps["sound"] = "default"
    return _post(token, {"aps": aps, **(data or {})}, "alert", "10")


def send_background(token: str, data: Dict[str, Any]) -> Tuple[bool, str]:
    """A silent push that wakes the app to sync (no alert, no sound); Apple may hold or drop
    it, and never delivers it to an app the user swiped away. Same answer as `send`."""
    return _post(token, {"aps": {"content-available": 1}, **data}, "background", "5")


def _post(token: str, payload: Dict[str, Any], push_type: str, priority: str) -> Tuple[bool, str]:
    if not is_configured():
        return False, "not_configured"
    token = (token or "").strip()
    if not token:
        return False, "no_token"

    provider = _provider_token()
    if not provider:
        return False, "no_provider_token"

    host = _SANDBOX_HOST if os.getenv("APNS_USE_SANDBOX", "").strip() in ("1", "true", "True") else _PROD_HOST
    try:
        resp = _http().post(
            f"{host}/3/device/{token}",
            headers={
                "authorization": f"bearer {provider}",
                "apns-topic": os.getenv("APNS_BUNDLE_ID", "").strip(),
                "apns-push-type": push_type,
                "apns-priority": priority,
            },
            content=json.dumps(payload).encode("utf-8"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[apns] send transport error: %s", exc)
        return False, "transport_error"

    if resp.status_code == 200:
        return True, "ok"
    reason = ""
    try:
        reason = (resp.json() or {}).get("reason", "")
    except Exception:  # noqa: BLE001
        reason = resp.text[:120]
    if resp.status_code == 410 or reason in ("BadDeviceToken", "Unregistered"):
        return False, "gone"
    logger.warning("[apns] send failed %s: %s", resp.status_code, reason)
    return False, f"http_{resp.status_code}"
