"""Apple Push Notification service — token-based (.p8) sender (Phase 7).

This is the "when I pay, it just works" half: the code is complete and gated
behind four env vars. Until they're set, ``is_configured()`` is False, the
scheduler stays idle, and ``send()`` returns ("skipped", "not_configured") — so
the free in-app-card path runs today with zero Apple account and zero cost.

To activate, set (from the Apple Developer account, needs the paid membership):
  APNS_KEY_P8      the AuthKey_XXXX.p8 contents (or a path to the file)
  APNS_KEY_ID      the key's 10-char Key ID
  APNS_TEAM_ID     the 10-char Team ID
  APNS_BUNDLE_ID   the app bundle id (the APNs 'topic')
  APNS_USE_SANDBOX optional "1" to hit the sandbox host (dev builds)

Auth is a short-lived ES256 provider JWT (Apple caps it at ~1h; we refresh at
50 min). Delivery is HTTP/2, which httpx does when the 'h2' package is present.
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
    """The .p8 contents, read directly or from a path in APNS_KEY_P8."""
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
    """True only when every credential needed to actually deliver is present."""
    return bool(
        _key_p8()
        and os.getenv("APNS_KEY_ID", "").strip()
        and os.getenv("APNS_TEAM_ID", "").strip()
        and os.getenv("APNS_BUNDLE_ID", "").strip()
    )


def _provider_token() -> Optional[str]:
    """Cached ES256 provider JWT, refreshed every 50 minutes."""
    global _cached_token, _cached_at
    with _lock:
        now = time.time()
        if _cached_token and (now - _cached_at) < _TOKEN_TTL_S:
            return _cached_token
        try:
            import jwt  # PyJWT (already a dependency)
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
) -> Tuple[bool, str]:
    """Deliver one alert notification to one device token.

    Returns (ok, status): ("ok",) on 200, ("gone",) when APNs says the token is
    dead (caller should prune it), ("skipped",) when unconfigured, or an error
    label. Never raises.
    """
    if not is_configured():
        return False, "not_configured"
    token = (token or "").strip()
    if not token:
        return False, "no_token"

    provider = _provider_token()
    if not provider:
        return False, "no_provider_token"

    host = _SANDBOX_HOST if os.getenv("APNS_USE_SANDBOX", "").strip() in ("1", "true", "True") else _PROD_HOST
    payload: Dict[str, Any] = {"aps": {"alert": {"title": title, "body": body}, "sound": "default"}}
    if data:
        payload.update(data)

    try:
        resp = _http().post(
            f"{host}/3/device/{token}",
            headers={
                "authorization": f"bearer {provider}",
                "apns-topic": os.getenv("APNS_BUNDLE_ID", "").strip(),
                "apns-push-type": "alert",
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
    # A dead token: prune it so we stop paying to retry.
    if resp.status_code == 410 or reason in ("BadDeviceToken", "Unregistered"):
        return False, "gone"
    logger.warning("[apns] send failed %s: %s", resp.status_code, reason)
    return False, f"http_{resp.status_code}"
