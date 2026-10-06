"""Optional Sentry error tracking; a no-op without SENTRY_DSN.

Privacy: no PII, no request bodies or query strings, no frame variables, secrets
scrubbed, breadcrumb text dropped; performance traces go through the same scrubber.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_started = False

# Matched as case-insensitive substrings of header/field names.
_SENSITIVE = (
    "authorization", "cookie", "token", "secret", "password", "passwd",
    "api_key", "apikey", "jwt", "hmac", "credential", "mongodb_uri", "dsn",
)


def _float(value: str, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _looks_sensitive(key: str) -> bool:
    # Strip separators so api_key / api-key / X-Api-Key all match.
    k = str(key).lower().replace("-", "").replace("_", "").replace(" ", "")
    return any(marker.replace("_", "") in k for marker in _SENSITIVE)


def _scrub(obj: Any, depth: int = 0) -> Any:
    """Recursively replace sensitive values; depth-limited against cycles."""
    if depth > 6:
        return obj
    if isinstance(obj, dict):
        return {
            k: ("[scrubbed]" if _looks_sensitive(k) else _scrub(v, depth + 1))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_scrub(v, depth + 1) for v in obj[:50]]
    return obj


def _log_tag(message: Any) -> str:
    text = str(message or "")
    if text.startswith("[") and "]" in text:
        return text[: text.index("]") + 1]
    return "[redacted]"


def _drop_frame_vars(event: Dict[str, Any]) -> None:
    """A frame's variables are whatever was being worked on: the user's message, a photo."""
    for key in ("exception", "threads"):
        block = event.get(key)
        values = block.get("values") if isinstance(block, dict) else None
        for value in values if isinstance(values, list) else []:
            frames = ((value or {}).get("stacktrace") or {}).get("frames")
            for frame in frames if isinstance(frames, list) else []:
                if isinstance(frame, dict):
                    frame.pop("vars", None)


def _before_send(event: Dict[str, Any], hint: Any) -> Optional[Dict[str, Any]]:
    try:
        _drop_frame_vars(event)
        # Request bodies are users' journals and messages; never send them.
        request = event.get("request")
        if isinstance(request, dict):
            request.pop("data", None)
            request.pop("cookies", None)
            if isinstance(request.get("headers"), dict):
                request["headers"] = _scrub(request["headers"])
            request.pop("query_string", None)
        for key in ("extra", "contexts", "tags"):
            if key in event:
                event[key] = _scrub(event[key])
        # INFO breadcrumbs contain user text; keep only the "[tag]".
        crumbs = event.get("breadcrumbs")
        values = crumbs.get("values") if isinstance(crumbs, dict) else crumbs
        if isinstance(values, list):
            for crumb in values:
                if isinstance(crumb, dict):
                    crumb["message"] = _log_tag(crumb.get("message"))
                    crumb.pop("data", None)
        entry = event.get("logentry")
        if isinstance(entry, dict):
            entry.pop("params", None)
            entry.pop("formatted", None)
        return event
    except Exception:  # noqa: BLE001
        # Never send an unscrubbed event.
        return None


def init_error_tracking() -> bool:
    """Start Sentry if SENTRY_DSN is set and the SDK is installed; returns whether it did."""
    global _started
    if _started:
        return True

    from app.config import APP_ENV, RELEASE_COMMIT, SENTRY_DSN, SENTRY_TRACES_RATE

    dsn = SENTRY_DSN
    if not dsn:
        logger.info("[errors] SENTRY_DSN not set — error reporting off")
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
    except ImportError:
        logger.warning(
            "[errors] SENTRY_DSN is set but sentry-sdk is not installed — "
            "add sentry-sdk to requirements.txt"
        )
        return False

    try:
        sentry_sdk.init(
            dsn=dsn,
            environment=APP_ENV,
            release=RELEASE_COMMIT or None,
            integrations=[
                FlaskIntegration(),
                LoggingIntegration(level=logging.INFO, event_level=logging.WARNING),
            ],
            send_default_pii=False,
            include_local_variables=False,
            before_send=_before_send,
            before_send_transaction=_before_send,
            sample_rate=1.0,
            traces_sample_rate=_float(SENTRY_TRACES_RATE, 0.1),
            max_breadcrumbs=50,
        )
        _started = True
        logger.info("[errors] error reporting on (env=%s)", APP_ENV)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("[errors] failed to start: %s", e)
        return False

