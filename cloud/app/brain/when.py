"""Times the model hands the tools: `when`, `due`, `since`/`until`, `period`."""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Tuple

from app.utils.arabic_days import (
    find_day_in_text, has_explicit_time, next_weekday_date, parse_date_from_text,
    resolve_day_name_to_iso,
)
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


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def aware_utc(dt: datetime) -> datetime:
    """Stored times come back naive UTC from Mongo."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def local_text(dt: Optional[datetime]) -> str:
    """How the reply names a time: his clock, never UTC."""
    if dt is None:
        return ""
    return aware_utc(dt).astimezone(USER_TZ).strftime("%Y-%m-%d %H:%M")


_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_RELATIVE = re.compile(r"بعد|دقيق|دقايق|ساعات|ساعتين|يومين|أيام|ايام|اسبوع|أسبوع|شهر")
# The number after «الساعة»/«عال» is the hour; a bare number is only when there is none.
_MARKED = re.compile(r"(?:عال|ع ال|على ال|الساعة|الساعه|ساعة|ساعه)\s*(\d{1,2})(?:[:.](\d{2}))?")
_BARE = re.compile(r"(?<![\d:.])(\d{1,2})(?:[:.](\d{2}))?(?![\d:.])")
# «يوم 15»، «15 بالشهر»: a day of the month, not an hour («اليوم 5» is today at 5).
_MONTH_DAY = re.compile(r"(?<!ال)(?:\bيوم|\bبيوم)\s*(\d{1,2})(?![\d:.])|(\d{1,2})\s*(?:بالشهر|من الشهر|الشهر)")
# Whole words only: «مع» is not «م», «صالة» is not «ص».
_MORNING = {"الصبح", "صبح", "الصباح", "صباحا", "صباحاً", "الفجر", "ص"}
_EVENING = {"المسا", "مسا", "مساء", "مساءً", "مساءا", "بالليل", "الليل", "العصر", "الظهر",
            "المغرب", "العشا", "م"}
_NIGHT = {"بالليل", "الليل"}


def _month_day(day: int, minutes: int, now: datetime) -> Optional[date]:
    """That day of this month when its time is still ahead, else of the next month that has it."""
    year, month = now.year, now.month
    for _ in range(13):
        try:
            d = date(year, month, day)
        except ValueError:
            d = None
        if d is not None and datetime(d.year, d.month, d.day, tzinfo=USER_TZ) + timedelta(minutes=minutes) > now:
            return d
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return None


def _clock(text: str, now: Optional[datetime] = None) -> Optional[datetime]:
    """«عالخمسة»، «الساعة ٥ ونص»، «بكرا الساعة ٨ الصبح»، «الجمعة الساعة 5»، «يوم 15 الساعة 5»
    → the next such moment. With no morning/evening word, the nearest one still ahead
    (5 → 17:00 after 5am); on another day 1–6 is the afternoon and 7–11 the morning, and a
    day named keeps the time on that day."""
    t = " " + (text or "").translate(_DIGITS).strip() + " "
    month_day = _MONTH_DAY.search(t)
    if month_day:
        t = t[:month_day.start()] + " " + t[month_day.end():]
    if _RELATIVE.search(t):
        return None
    m = _MARKED.search(t) or _BARE.search(t)
    if not m or not 0 <= int(m.group(1)) <= 23:
        return None
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    if "ونص" in t:
        minute += 30
    elif "وربع" in t:
        minute += 15
    elif "الا ربع" in t or "إلا ربع" in t:
        minute -= 15
    words = set(re.sub(r"[^\w\s]", " ", t).split())
    if hour == 12:
        hours = [0] if words & _NIGHT else [12]          # «12 الظهر» is noon, «12 بالليل» midnight
    elif hour > 12 or words & _MORNING:
        hours = [hour]
    elif words & _EVENING:
        hours = [hour % 12 + 12]
    else:
        hours = [hour % 12, hour % 12 + 12]
    now = (now or datetime.now(USER_TZ)).astimezone(USER_TZ)
    weekday = find_day_in_text(" ".join(words))
    if month_day:
        first = _month_day(int(month_day.group(1) or month_day.group(2)), min(hours) * 60 + minute, now)
        if first is None:
            return None
        days = [first]
    elif weekday is not None:
        # That weekday: today only while the time is still ahead, else next week.
        first = next_weekday_date(weekday, reference=now.date(), allow_today=True)
        days = [first, first + timedelta(days=7)]
    else:
        first = now.date() + timedelta(days=1) if words & {"بكرا", "بكرة", "بكره", "غدا", "غداً"} else now.date()
        days = [first, first + timedelta(days=1)]
    for d in days:
        if len(hours) == 2 and d != now.date():
            # Another day with no morning/evening word: 1–6 is the afternoon, 7–11 the morning.
            hours = [hours[1]] if 1 <= hour <= 6 else [hours[0]]
        for h in hours:
            at = datetime(d.year, d.month, d.day, tzinfo=USER_TZ) + timedelta(hours=h, minutes=minute)
            if at > now:
                return at.astimezone(timezone.utc)
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
    clock = _clock(text)
    if clock is not None:
        return clock
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
    """[start, end) in UTC for a named period, in the user's calendar: «هالأسبوع» is from
    Saturday (the week runs Saturday to Friday), «هالشهر» from the 1st, «هالسنة» from January, each up to the end of today."""
    now = (now or datetime.now(USER_TZ)).astimezone(USER_TZ)
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = day + timedelta(days=1)
    if period == "yesterday":
        start, end = day - timedelta(days=1), day
    elif period == "week":
        start = day - timedelta(days=(day.weekday() - 5) % 7)
    elif period == "month":
        start = day.replace(day=1)
    elif period == "year":
        start = day.replace(month=1, day=1)
    else:
        start = day
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
