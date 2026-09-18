"""Per-account quota for every route that spends money on a provider.

It lived as a closure inside `server.create_app`, shared by the two chat routes
and nothing else — so every other route that calls a paid service (web and
place search, page fetch, gift writing, studio summaries, photo tagging, image
generation) reached Exa, Google or Azure with no limit at all for a signed-in
free account. One module means one tier table and one set of messages, and a
route that forgets to meter is a route that did not import this.

A metered call is one unit against the same daily and per-minute budget as a
chat message: the quota is on what an account costs, not on which screen it
came from.
"""
from __future__ import annotations

from typing import Optional, Tuple

# (daily, per minute). The owner and subscribers share the top tier.
SUBSCRIBER_DAILY, SUBSCRIBER_PER_MIN = 5000, 60
FREE_DAILY, FREE_PER_MIN = 40, 12

# What each rejection code means, in words a person can read. `check_and_record`
# returns a machine code — right for the store, wrong as the only field, because
# the app shows whatever it finds and a user was told "daily_quota_exceeded".
_LIMIT_MESSAGES = {
    "rate_limited": "شوي شوي 😄 وصلت للحد بهالدقيقة — جرّب بعد شوي.",
    "daily_quota_exceeded": "خلص رصيدك لليوم. بيرجع بكرا، أو رقّي اشتراكك.",
}


def meter_or_error(role: str, user_id: str) -> Optional[str]:
    """Record one unit for this account. The error code if it is over, else None."""
    from app.features import usage_store, users_store

    if role == "owner" or users_store.is_subscriber(user_id):
        daily, per_min = SUBSCRIBER_DAILY, SUBSCRIBER_PER_MIN
    else:
        daily, per_min = FREE_DAILY, FREE_PER_MIN
    return usage_store.check_and_record(
        user_id, daily_limit=daily, per_min_limit=per_min
    )


def limit_response(code: str) -> dict:
    """The 429 body: the code to branch on and the sentence to show."""
    return {
        "error": code,
        "message": _LIMIT_MESSAGES.get(code, "وصلت للحد المسموح — جرّب لاحقاً."),
    }


def meter_claims(claims: dict) -> Optional[Tuple[dict, int]]:
    """Meter a signed-in caller from their token. A ready ``(body, 429)`` refusal,
    or None to proceed. Guests are not metered here — the routes that serve them
    either return demo data or have their own visitor budget."""
    if (claims or {}).get("role", "guest") == "guest":
        return None
    over = meter_or_error(claims.get("role", "user"), str(claims.get("user_id") or ""))
    if over:
        return limit_response(over), 429
    return None
