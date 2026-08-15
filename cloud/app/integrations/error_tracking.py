"""Error tracking — so a failure in production is something you are told about.

The case for this is not theoretical. The voice link broke on 14 Aug and stayed
broken through a whole afternoon; it was found because the owner picked the robot
up and tried to talk to it. Three hypotheses were chased and two of them were
wrong before a serial log finally showed a single timed-out socket write. Every
one of those errors was logged, on a dyno, into a buffer nobody was reading.

What this changes: the first user to hit a bug generates a report with the
stack, the request, the release, and how many others hit the same thing. Nobody
has to notice.

Optional by design. With no `SENTRY_DSN` the whole module is a no-op and the app
behaves exactly as it did before — same as every other integration here. It is
never a reason the backend fails to boot.

Privacy is the part worth being deliberate about. This system holds
conversations, journals, memories and voiceprints, and an error tracker that
helpfully attaches request bodies would quietly ship those to a third party. So:
`send_default_pii=False`, request bodies never attached, and a scrubber that
drops anything that looks like a secret before it leaves the process.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_started = False

# Header and field names that must never leave this process. Matched as
# substrings, case-insensitively, so `X-Auth-Token` and `authorization` both go.
_SENSITIVE = (
    "authorization", "cookie", "token", "secret", "password", "passwd",
    "api_key", "apikey", "jwt", "hmac", "credential", "mongodb_uri", "dsn",
)


def _float(value: str, fallback: float) -> float:
    """A misconfigured rate must not stop the app from booting."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _looks_sensitive(key: str) -> bool:
    # Separators are normalised away first. The same idea gets written
    # `api_key`, `api-key`, `apiKey` and `X-Api-Key` depending on whether it is
    # a header, a form field or a variable, and a scrubber that only matches one
    # spelling is a scrubber that leaks the other three. A test caught exactly
    # that: `X-Api-Key` sailed straight through.
    k = str(key).lower().replace("-", "").replace("_", "").replace(" ", "")
    return any(marker.replace("_", "") in k for marker in _SENSITIVE)


def _scrub(obj: Any, depth: int = 0) -> Any:
    """Recursively replace sensitive values with a marker.

    Depth-limited: an event is a nested structure from a library we do not
    control, and a cycle or a pathological depth here would hang the reporting
    thread — which would turn error tracking into an outage of its own.
    """
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


def _before_send(event: Dict[str, Any], hint: Any) -> Optional[Dict[str, Any]]:
    """Last gate before an event leaves the process."""
    try:
        # A request body on this backend is somebody's journal entry or the
        # message they just spoke. It is never worth the debugging value.
        request = event.get("request")
        if isinstance(request, dict):
            request.pop("data", None)
            request.pop("cookies", None)
            if isinstance(request.get("headers"), dict):
                request["headers"] = _scrub(request["headers"])
            # Query strings can carry ids; the path alone is enough to locate a bug.
            request.pop("query_string", None)
        for key in ("extra", "contexts", "tags"):
            if key in event:
                event[key] = _scrub(event[key])
        return event
    except Exception:  # noqa: BLE001
        # A scrubber that throws must not send the unscrubbed event. Dropping it
        # loses one report; the alternative leaks user data.
        return None


def init_error_tracking() -> bool:
    """Start Sentry if it is configured. Returns whether it did.

    Safe to call more than once and safe to call with the package absent — this
    is an optional dependency, so a deployment that has not installed it simply
    runs without reporting.
    """
    global _started
    if _started:
        return True

    # Every environment variable is read through app.config, never at a call
    # site — one place answers "what does this deployment need?", and a guard
    # test enforces it. (That guard counts the pattern in comments too, which is
    # how this comment ended up phrased the long way round.)
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
            # Ties a report to the exact build. Without it, "which version broke?"
            # is guesswork, and on a platform that redeploys on every push it is
            # guesswork you do often.
            release=RELEASE_COMMIT or None,
            integrations=[
                FlaskIntegration(),
                # WARNING and above becomes a report; INFO stays breadcrumbs, so
                # a report arrives with the story leading up to it rather than a
                # bare stack.
                LoggingIntegration(level=logging.INFO, event_level=logging.WARNING),
            ],
            # Never attach usernames, emails, or IPs.
            send_default_pii=False,
            before_send=_before_send,
            # Errors are always reported. Performance traces are sampled at a
            # tenth: enough shape to see a slow endpoint, cheap enough to leave on.
            sample_rate=1.0,
            traces_sample_rate=_float(SENTRY_TRACES_RATE, 0.1),
            max_breadcrumbs=50,
        )
        _started = True
        logger.info("[errors] error reporting on (env=%s)", APP_ENV)
        return True
    except Exception as e:  # noqa: BLE001
        # Reporting is a convenience. It may never be the reason the app is down.
        logger.warning("[errors] failed to start: %s", e)
        return False


def capture(message: str, **context: Any) -> None:
    """Report something that went wrong but did not raise.

    For the failures that return a safe default instead of throwing — a
    circuit-breaker opening, a heartbeat that will not parse, an actuation that
    was refused. Those never reach an exception handler, so without this they are
    invisible.
    """
    if not _started:
        return
    try:
        import sentry_sdk

        with sentry_sdk.push_scope() as scope:
            for key, value in _scrub(context).items():
                scope.set_extra(key, value)
            sentry_sdk.capture_message(message, level="warning")
    except Exception:  # noqa: BLE001
        pass
