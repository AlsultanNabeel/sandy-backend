"""Typed application errors; create_app turns them into {"error": <code>} with their HTTP status."""

from __future__ import annotations

from typing import Optional


class SandyError(Exception):
    """Base error: an HTTP ``http_status`` and a stable ``code``, both overridable per raise."""

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
    """Required config is missing (503: retry once configured)."""

    http_status = 503
    code = "not_configured"


