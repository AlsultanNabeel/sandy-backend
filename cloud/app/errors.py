"""Typed error taxonomy for the backend.

Before this, a failure was either a bare ``raise RuntimeError(...)`` or an ad-hoc
``return jsonify({"error": "..."}), code`` copied per endpoint. This gives one
base — :class:`SandyError` — carrying an HTTP status and a stable machine code,
plus a small set of subtypes for the common failure shapes. Raise one of these
from anywhere on a request path and the Flask handler registered in
``create_app`` turns it into a consistent ``{"error": <code>}`` response with the
right status.

Broad ``except Exception`` still has its place — optional integrations,
background jobs, index creation — where the right move is log-and-continue, not
surface. This taxonomy is for the failures the caller *should* see, so those
sites can raise intent instead of hand-rolling a status code.
"""

from __future__ import annotations

from typing import Optional


class SandyError(Exception):
    """Base for every typed application error.

    Carries the HTTP ``http_status`` and a stable machine-readable ``code`` the
    client can branch on. Subclasses set sensible defaults; either can be
    overridden per-raise.
    """

    http_status: int = 500
    code: str = "internal_error"

    def __init__(
        self,
        message: str = "",
        *,
        code: Optional[str] = None,
        http_status: Optional[int] = None,
    ):
        super().__init__(message or (code or self.code))
        if code is not None:
            self.code = code
        if http_status is not None:
            self.http_status = http_status


class ValidationError(SandyError):
    """The request/input was malformed or failed a precondition."""

    http_status = 400
    code = "invalid_request"


class AuthError(SandyError):
    """Missing or invalid credentials for an authenticated action."""

    http_status = 401
    code = "unauthorized"


class ForbiddenError(SandyError):
    """Authenticated but not allowed (e.g. a guest hitting a mutating route)."""

    http_status = 403
    code = "forbidden"


class NotFoundError(SandyError):
    """The addressed resource does not exist for this tenant."""

    http_status = 404
    code = "not_found"


class RateLimitError(SandyError):
    """Too many attempts inside the window."""

    http_status = 429
    code = "too_many_attempts"


class ConfigError(SandyError):
    """A required secret/credential/config is missing — the app or a feature
    cannot run. 503: retry once the operator fixes configuration."""

    http_status = 503
    code = "not_configured"


class ExternalServiceError(SandyError):
    """A dependency (model provider, MQTT, room device, ...) failed in a way the
    caller should see rather than a silent fallback."""

    http_status = 502
    code = "upstream_failed"
