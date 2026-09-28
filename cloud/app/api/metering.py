"""Per-account quota for chat and every route that spends money on a provider.

One unit per call against the same daily/per-minute budget as a chat message.
"""
from __future__ import annotations

from typing import Optional, Tuple

# (daily, per minute). The owner and subscribers share the top tier.
SUBSCRIBER_DAILY, SUBSCRIBER_PER_MIN = 5000, 60
FREE_DAILY, FREE_PER_MIN = 40, 12

# The app shows the message; the code is for branching.
_LIMIT_MESSAGES = {
    "rate_limited": "شوي شوي 😄 وصلت للحد بهالدقيقة — جرّب بعد شوي.",
    "daily_quota_exceeded": "خلص رصيدك لليوم. بيرجع بكرا، أو رقّي اشتراكك.",
}


def meter_or_error(role: str, user_id: str) -> Optional[str]:
    """Record one unit; the error code if over the limit, else None."""
    from app.features import usage_store, users_store

    if role == "owner" or users_store.is_subscriber(user_id):
        daily, per_min = SUBSCRIBER_DAILY, SUBSCRIBER_PER_MIN
    else:
        daily, per_min = FREE_DAILY, FREE_PER_MIN
    return usage_store.check_and_record(
        user_id, daily_limit=daily, per_min_limit=per_min
    )


def limit_response(code: str) -> dict:
    return {
        "error": code,
        "message": _LIMIT_MESSAGES.get(code, "وصلت للحد المسموح — جرّب لاحقاً."),
    }


def meter_claims(claims: dict) -> Optional[Tuple[dict, int]]:
    """Meter a signed-in caller: a ready ``(body, 429)`` refusal, or None. Guests aren't metered here."""
    if (claims or {}).get("role", "guest") == "guest":
        return None
    over = meter_or_error(claims.get("role", "user"), str(claims.get("user_id") or ""))
    if over:
        return limit_response(over), 429
    return None
