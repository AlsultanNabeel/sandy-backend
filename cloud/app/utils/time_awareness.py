"""Sandy's sense of *when* — the same few lines for every channel.

A reply written without the clock is written from nowhere: the model does not
know it is 5 pm, that it is Sunday, or that the person last spoke to her three
days ago. Two things followed from that. Small ones — "good morning" at night,
no reaction to someone coming back after a week. And a real bug: the router
fills a tool's ISO date field itself, and without today's date it picked a date
from its training years, so "remind me at 5 pm" came back "that time is in the
past".

Every turn now carries three facts, built here once:

- **now** — weekday, date, time and the ISO timestamp (for tool arguments);
- **the gap** — how long since the previous message, on which channel;
- **per-turn stamps** — for transcripts shown to the model ("قبل ساعتين · الروبوت").

Latin digits on purpose: this text is read by a model, never shown to a person.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, Optional

from app.utils.arabic_days import WEEKDAY_TO_AR_NAME
from app.utils.time import USER_TIMEZONE, USER_TZ

# A model-supplied date further out than this is treated as a guess, not a plan.
_PLAUSIBLE_HORIZON = timedelta(days=400)


def _now(now: Optional[datetime] = None) -> datetime:
    return (now or datetime.now(USER_TZ)).astimezone(USER_TZ)


def _clock(dt: datetime) -> str:
    """`5:07 م` — 12-hour Arabic clock."""
    h = dt.hour % 12 or 12
    return f"{h}:{dt.minute:02d} {'ص' if dt.hour < 12 else 'م'}"


def parse_ts(value: Any) -> Optional[datetime]:
    """A stored turn timestamp (ISO string or datetime) in the user's zone."""
    if not value:
        return None
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(
            str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        from datetime import timezone
        dt = dt.replace(tzinfo=timezone.utc)   # stored naive == UTC (Mongo)
    return dt.astimezone(USER_TZ)


def ago_ar(delta: timedelta) -> str:
    """`قبل 3 ساعات و10 دقائق` — coarse on purpose; precision is noise here."""
    secs = int(delta.total_seconds())
    if secs < 90:
        return "قبل لحظات"
    mins = secs // 60
    if mins < 60:
        return f"قبل {mins} دقيقة"
    hours, mins = divmod(mins, 60)
    if hours < 24:
        return f"قبل {hours} ساعة" + (f" و{mins} دقيقة" if mins >= 5 else "")
    days, hours = divmod(hours, 24)
    if days < 14:
        return f"قبل {days} يوم" + (f" و{hours} ساعة" if days < 3 and hours else "")
    return f"قبل {days // 7} أسبوع"


def when_ar(dt: datetime, now: Optional[datetime] = None) -> str:
    """`اليوم 5:07 م` / `أمس 11:40 م` / `الخميس 17/09 9:00 ص`."""
    now = _now(now)
    dt = dt.astimezone(USER_TZ)
    days = (now.date() - dt.date()).days
    if days == 0:
        day = "اليوم"
    elif days == 1:
        day = "أمس"
    else:
        day = f"{WEEKDAY_TO_AR_NAME.get(dt.weekday(), '')} {dt:%d/%m}"
    return f"{day} {_clock(dt)}"


def now_line(now: Optional[datetime] = None) -> str:
    now = _now(now)
    return (f"الآن: {WEEKDAY_TO_AR_NAME.get(now.weekday(), '')} {now:%d/%m/%Y} "
            f"الساعة {_clock(now)} (توقيت {USER_TIMEZONE}) — ISO: "
            f"{now.replace(microsecond=0).isoformat()}")


def _last_turn(history: Optional[Iterable[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    best, best_ts = None, None
    for m in history or []:
        ts = parse_ts(m.get("timestamp"))
        if ts is not None and (best_ts is None or ts > best_ts):
            best, best_ts = m, ts
    return best


def last_contact_line(history: Optional[Iterable[Dict[str, Any]]],
                      now: Optional[datetime] = None) -> str:
    """How long since the previous message, and where it happened."""
    last = _last_turn(history)
    if last is None:
        return "ما في محادثة قريبة محفوظة قبل هاي الرسالة."
    now = _now(now)
    ts = parse_ts(last.get("timestamp"))
    via = str(last.get("via") or "").strip()
    return (f"آخر تواصل قبل هاي الرسالة: {ago_ar(now - ts)} ({when_ar(ts, now)}"
            + (f"، عبر {via}" if via else "") + ").")


def time_awareness_block(history: Optional[Iterable[Dict[str, Any]]] = None,
                         now: Optional[datetime] = None) -> str:
    """The block every reply prompt carries. Tells her *how* to use it, too —
    a clock she recites in every answer is worse than no clock."""
    return (
        f"[{now_line(now)}]\n[{last_contact_line(history, now)}]\n"
        "استعملي إدراك الوقت بشكل طبيعي: التحية حسب الوقت، ولو غاب فترة طويلة "
        "لاحظي هاد بلطف، وحسبة المواعيد («بكرا»، «الساعة 5») من الوقت الحالي. "
        "ما تذكري الساعة أو المدة إلا لما يكون إلها معنى بالرد."
    )


def turn_stamp(m: Dict[str, Any], now: Optional[datetime] = None) -> str:
    """`قبل ساعتين · الروبوت` for a transcript line, or '' when unknown."""
    ts = parse_ts(m.get("timestamp"))
    if ts is None:
        return ""
    via = str(m.get("via") or "").strip()
    return ago_ar(_now(now) - ts) + (f" · {via}" if via else "")


def plausible_future_iso(iso: str, now: Optional[datetime] = None) -> bool:
    """Is a model-supplied ISO time one to trust as-is?

    True only for a parseable time that is in the future and within about a
    year. Anything else — the past, or a date from another decade — is the
    router guessing, and the caller should re-read the user's own words.
    """
    if not iso:
        return False
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=USER_TZ)
    now = _now(now)
    if dt > now + _PLAUSIBLE_HORIZON:
        return False
    local = dt.astimezone(USER_TZ)
    if (local.hour, local.minute, local.second) == (0, 0, 0):
        # Date only ("today", "Friday"): the callers fill in a default hour,
        # so a date of today is still the user's date, not a past time.
        return local.date() >= now.date()
    return dt > now
