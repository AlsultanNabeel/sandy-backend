"""Per-account quota for chat and every route that spends money on a provider.

One unit per call against the same daily/per-minute budget as a chat message.
"""
from __future__ import annotations

import os
from typing import Optional, Tuple

# (daily, per minute). The owner (by token or by account) and subscribers share the top tier.
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


def _limits(role: str, user_id: str) -> Tuple[int, int]:
    from app.features import users_store

    if role == "owner" or is_owner_account(user_id) or users_store.is_subscriber(user_id):
        return SUBSCRIBER_DAILY, SUBSCRIBER_PER_MIN
    return FREE_DAILY, FREE_PER_MIN


def meter_or_error(role: str, user_id: str) -> Optional[str]:
    """Record one unit; the error code if over the limit, else None."""
    from app.features import usage_store

    daily, per_min = _limits(role, user_id)
    return usage_store.check_and_record(
        user_id, daily_limit=daily, per_min_limit=per_min
    )


def over_limit(role: str, user_id: str) -> Optional[str]:
    """The error code if one more unit would be past the limit; nothing is recorded (the
    caller charges with `meter_or_error` once the work succeeded)."""
    from app.features import usage_store

    daily, per_min = _limits(role, user_id)
    return usage_store.over_limit(user_id, daily_limit=daily, per_min_limit=per_min)


def is_owner_account(user_id: str) -> bool:
    """The account itself is marked the project owner's in the settings (SANDY_OWNER_ACCOUNTS),
    however it signed in."""
    from app import config

    wanted = {u.strip() for u in config.SANDY_OWNER_ACCOUNTS.split(",") if u.strip()}
    return bool(user_id) and user_id in wanted


def voice_seconds_left(user_id: str) -> float:
    """Seconds of voice this account has left today: the subscriber's cap for a subscriber or
    the owner's account, by the account and never by how it signed in."""
    from app.features import usage_store, users_store

    top = is_owner_account(user_id) or users_store.is_subscriber(user_id)
    cap = CALL_MINUTES_SUBSCRIBER if top else CALL_MINUTES_FREE
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
