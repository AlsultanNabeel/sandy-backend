"""Times the model hands the tools: `when`, `due`, `since`/`until`, `period`."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from app.utils.arabic_days import has_explicit_time, parse_date_from_text, resolve_day_name_to_iso
from app.utils.nlp_normalizer import normalize_user_message
from app.utils.time import USER_TZ
from app.utils.time_awareness import plausible_future_iso

logger = logging.getLogger(__name__)

PERIODS = ("today", "yesterday", "week", "month", "year")
RECURRENCES = {"daily": "FREQ=DAILY", "weekly": "FREQ=WEEKLY",
               "monthly": "FREQ=MONTHLY", "yearly": "FREQ=YEARLY"}


_PARSE_SYSTEM = (
    "Convert reminder/time expressions to JSON only."
    "Return fields: success (boolean), remind_at_iso (string|null), intent (one of 'reminder','calendar','task','unknown'), reason (string), original_text (string)."
    "If no time can be inferred set success=false and provide a reason."
    "If a date is given but no time, default to 09:00:00 in the user's timezone."
    "Use the provided current datetime as reference and output full ISO format."
)


def _chat_fn():
    """The shared chat client (C4); None without credentials."""
    from app.integrations.openai_client import chat_fn
    try:
        return chat_fn()
    except Exception as exc:  # noqa: BLE001 — no key only disables the AI parse
        logger.info("[brain] no model for time parsing: %s", exc)
        return None


def _parse_with_model(text: str) -> Optional[str]:
    """ISO in the user's zone for a time expression: a bare weekday without a
    model, else one JSON call. None when unreadable or in the past."""
    normalized = normalize_user_message(text)
    if not normalized:
        return None
    now = datetime.now(USER_TZ)
    day = resolve_day_name_to_iso(normalized)
    if day and datetime.fromisoformat(day) > now:
        return day
    complete = _chat_fn()
    if complete is None:
        return None
    try:
        response = complete(
            temperature=0, max_tokens=140, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": _PARSE_SYSTEM},
                      {"role": "user", "content": (f"current_datetime={now.isoformat()}\n"
                                                   f"raw_text={text}\n"
                                                   f"normalized_text={normalized}")}])
        payload = json.loads(response.choices[0].message.content or "{}")
        iso_value = str(payload.get("remind_at_iso") or "").strip()
        if not payload.get("success") or not iso_value:
            logger.info("[brain] time not parsed: %s", payload.get("reason") or "unknown")
            return None
        dt = _aware(datetime.fromisoformat(iso_value)).astimezone(USER_TZ)
    except Exception as exc:  # noqa: BLE001 — provider boundary; the caller refuses instead
        logger.warning("[brain] time parse failed: %s", exc)
        return None
    return dt.isoformat() if dt >= now else None


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=USER_TZ) if dt.tzinfo is None else dt


def parse_when(text: str) -> Optional[datetime]:
    """A future moment (UTC) from ISO or words ("بكرا الساعة 5"), else None."""
    text = str(text or "").strip()
    if not text:
        return None
    if plausible_future_iso(text):
        dt = _aware(datetime.fromisoformat(text.replace("Z", "+00:00"))).astimezone(USER_TZ)
        if (dt.hour, dt.minute, dt.second) == (0, 0, 0):
            dt = dt.replace(hour=9)  # a date with no time, same default as arabic_days
        return dt.astimezone(timezone.utc)
    iso = _parse_with_model(text)
    if not iso and not has_explicit_time(text):
        # Day-only phrases still resolve without a model; a clock time never falls to 9am.
        iso = parse_date_from_text(normalize_user_message(text))
    if not iso:
        return None
    return _aware(datetime.fromisoformat(iso)).astimezone(timezone.utc)


def parse_bound(text: str, *, end: bool = False) -> Optional[datetime]:
    """``since``/``until``: an ISO date or datetime; a bare date covers its whole day."""
    text = str(text or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if len(text) <= 10 and end:
        dt = dt + timedelta(days=1)
    return _aware(dt).astimezone(timezone.utc)


def period_range(period: str, now: Optional[datetime] = None) -> Tuple[datetime, datetime]:
    """[start, end) in UTC for a named period, in the user's calendar."""
    now = (now or datetime.now(USER_TZ)).astimezone(USER_TZ)
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "yesterday":
        start, end = day - timedelta(days=1), day
    elif period == "week":
        start, end = day - timedelta(days=6), day + timedelta(days=1)
    elif period == "month":
        start, end = day - timedelta(days=29), day + timedelta(days=1)
    elif period == "year":
        start, end = day - timedelta(days=364), day + timedelta(days=1)
    else:
        start, end = day, day + timedelta(days=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def recurrence_rule(value: str) -> Optional[str]:
    """RRULE for a named repeat or a raw ``FREQ=`` rule; None when unreadable."""
    v = str(value or "").strip()
    if not v:
        return ""
    if v.lower() in RECURRENCES:
        return RECURRENCES[v.lower()]
    return v.upper() if v.upper().startswith("FREQ=") else None


def iso(dt: Optional[datetime]) -> str:
    if not isinstance(dt, datetime):
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)  # Mongo hands back naive UTC
    return dt.astimezone(USER_TZ).replace(microsecond=0).isoformat()
