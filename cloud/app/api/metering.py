"""Per-account quota for chat and every route that spends money on a provider.

One unit per call against the same daily/per-minute budget as a chat message.
"""
from __future__ import annotations

import os
from typing import Optional, Tuple

# (daily, per minute). The owner and subscribers share the top tier.
SUBSCRIBER_DAILY, SUBSCRIBER_PER_MIN = 5000, 60
FREE_DAILY, FREE_PER_MIN = 40, 12
# Minutes of voice a day (live calls on the app or the robot, and replies read aloud), from
# the settings; a subscriber's (and the owner's) is higher.
CALL_MINUTES_FREE = float(os.getenv("SANDY_CALL_MINUTES_FREE", "10"))
CALL_MINUTES_SUBSCRIBER = float(os.getenv("SANDY_CALL_MINUTES_SUBSCRIBER", "60"))

# The app shows the message; the code is for branching.
_LIMIT_MESSAGES = {
    "rate_limited": "شوي شوي 😄 وصلت للحد بهالدقيقة — جرّب بعد شوي.",
    "daily_quota_exceeded": "خلص رصيدك لليوم. بيرجع بكرا، أو رقّي اشتراكك.",
    "call_minutes_exceeded": "خلصت دقايق الحكي لليوم. بترجع بكرا، أو رقّي اشتراكك.",
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


def _top_tier(user_id: str, role: Optional[str]) -> bool:
    """The owner or a subscriber. Without a token's role (a call), the owner is read from the
    account as sign-in grants it: a Google/Apple sign-in on an owner address."""
    from app.features import users_store

    if role == "owner" or users_store.is_subscriber(user_id):
        return True
    if role is None:
        from app.api.auth_handlers import role_for_email

        user = users_store.get_user(user_id) or {}
        return (user.get("provider") in ("google", "apple")
                and role_for_email(str(user.get("email") or "")) == "owner")
    return False


def voice_seconds_left(user_id: str, role: Optional[str] = None) -> float:
    """Seconds of voice this user has left today. `role` is the token's when there is one."""
    from app.features import usage_store

    cap = CALL_MINUTES_SUBSCRIBER if _top_tier(user_id, role) else CALL_MINUTES_FREE
    return max(0.0, cap * 60 - usage_store.voice_seconds_today(user_id))


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
