"""Times the model hands the tools: `when`, `due`, `since`/`until`, `period`."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from app.features.time_parser import parse_reminder_time_ai
from app.utils.arabic_days import has_explicit_time, parse_date_from_text
from app.utils.nlp_normalizer import normalize_user_message
from app.utils.time import USER_TZ
from app.utils.time_awareness import plausible_future_iso

logger = logging.getLogger(__name__)

PERIODS = ("today", "yesterday", "week", "month", "year")
RECURRENCES = {"daily": "FREQ=DAILY", "weekly": "FREQ=WEEKLY",
               "monthly": "FREQ=MONTHLY", "yearly": "FREQ=YEARLY"}


def _chat_fn():
    # The old agent's singleton client (C4); None without credentials.
    from app.agent.nodes.execute import _get_chat_completion_fn
    try:
        return _get_chat_completion_fn()
    except Exception as exc:  # noqa: BLE001 — no key only disables the AI parse
        logger.info("[brain] no model for time parsing: %s", exc)
        return None


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
    iso = parse_reminder_time_ai(text, create_chat_completion_fn=_chat_fn())
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
