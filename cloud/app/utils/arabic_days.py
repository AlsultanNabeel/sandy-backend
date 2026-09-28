"""Arabic day-name variants → Python weekday (0=Monday … 6=Sunday)."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Optional

from app.utils.time import USER_TZ

DAY_NAME_TO_WEEKDAY: dict[str, int] = {
    # Sunday = 6
    "أحد": 6,
    "احد": 6,
    "الأحد": 6,
    "الاحد": 6,
    # Monday = 0
    "اثنين": 0,
    "اتنين": 0,
    "إثنين": 0,
    "إتنين": 0,
    "الاثنين": 0,
    "الاتنين": 0,
    "الإثنين": 0,
    "الإتنين": 0,
    # Tuesday = 1
    "ثلاثاء": 1,
    "ثلاثا": 1,
    "تلاتاء": 1,
    "تلاتا": 1,
    "تلاثاء": 1,
    "تلاثا": 1,
    "الثلاثاء": 1,
    "الثلاثا": 1,
    "التلاتاء": 1,
    "التلاتا": 1,
    "التلاثاء": 1,
    "التلاثا": 1,
    # Wednesday = 2
    "أربعاء": 2,
    "اربعاء": 2,
    "أربعا": 2,
    "اربعا": 2,
    "الأربعاء": 2,
    "الاربعاء": 2,
    "الأربعا": 2,
    "الاربعا": 2,
    # Thursday = 3
    "خميس": 3,
    "الخميس": 3,
    # Friday = 4
    "جمعة": 4,
    "جمعه": 4,
    "الجمعة": 4,
    "الجمعه": 4,
    # Saturday = 5
    "سبت": 5,
    "السبت": 5,
}

WEEKDAY_TO_AR_NAME: dict[int, str] = {
    0: "الاثنين",
    1: "الثلاثاء",
    2: "الأربعاء",
    3: "الخميس",
    4: "الجمعة",
    5: "السبت",
    6: "الأحد",
}

# Tokens suggesting a free-text due/reminder string names a day or date.
DATE_HINT_TOKENS: tuple[str, ...] = (
    "اليوم",
    "بكرة",
    "بكره",
    "غدا",
    "غداً",
    "بعد",
    "الأحد",
    "الاحد",
    "الاثنين",
    "الثلاثاء",
    "الأربعاء",
    "الاربعاء",
    "الخميس",
    "الجمعة",
    "الجمعه",
    "السبت",
    "today",
    "tomorrow",
    "next",
    "/",
    "-",
)

_EXPLICIT_TIME_PAT = re.compile(
    r"الساعة|ساعة|صباحاً|مساءً|صباح|مساء|الصبح|الضهر|الظهر|المساء|الليل"
    r"|\d+\s*:\s*\d+|\d+\s*(?:am|pm)",
    re.IGNORECASE,
)


def _iso_at(d: date, hour: int) -> str:
    return datetime(d.year, d.month, d.day, hour, 0, 0, tzinfo=USER_TZ).isoformat()


def _iso_or_none(y: int, mo: int, d: int, hour: int) -> Optional[str]:
    try:
        return datetime(y, mo, d, hour, 0, 0, tzinfo=USER_TZ).isoformat()
    except ValueError:
        return None


def find_day_in_text(text: str) -> Optional[int]:
    for token in text.split():
        token = token.strip("،.,!؟'\"()[]")
        wd = DAY_NAME_TO_WEEKDAY.get(token)
        if wd is not None:
            return wd
    return None


def has_explicit_time(text: str) -> bool:
    return bool(_EXPLICIT_TIME_PAT.search(text))


def next_weekday_date(
    weekday: int,
    *,
    reference: Optional[date] = None,
    allow_today: bool = False,
) -> date:
    """Next occurrence of *weekday*; same day counts only with allow_today."""
    ref = reference or datetime.now(USER_TZ).date()
    days_ahead = (weekday - ref.weekday()) % 7
    if days_ahead == 0 and not allow_today:
        days_ahead = 7
    return ref + timedelta(days=days_ahead)


def resolve_day_name_to_iso(
    text: str,
    *,
    default_hour: int = 9,
    reference: Optional[date] = None,
) -> Optional[str]:
    """ISO datetime for a day name in *text*, or None if absent or a clock time is given."""
    if has_explicit_time(text):
        return None
    weekday = find_day_in_text(text)
    if weekday is None:
        return None
    return _iso_at(next_weekday_date(weekday, reference=reference), default_hour)


def parse_numeric_date(text: str, *, default_hour: int = 9) -> Optional[str]:
    """YYYY/MM/DD, DD/MM/YYYY, YYYYMMDD or DDMMYYYY (any of - / . _ ,) → ISO, else None."""
    if not text:
        return None
    s = re.sub(r"[\\._,]", "-", text.strip())

    m = re.search(r"(20\d{2}|19\d{2})[-/](\d{1,2})[-/](\d{1,2})", s)
    if m:
        return _iso_or_none(int(m.group(1)), int(m.group(2)), int(m.group(3)), default_hour)

    m = re.search(r"(\d{1,2})[-/](\d{1,2})[-/](20\d{2}|19\d{2})", s)
    if m:
        return _iso_or_none(int(m.group(3)), int(m.group(2)), int(m.group(1)), default_hour)

    m = re.search(r"(\d{8})", s)
    if m:
        v = m.group(1)
        return (_iso_or_none(int(v[0:4]), int(v[4:6]), int(v[6:8]), default_hour)
                or _iso_or_none(int(v[4:8]), int(v[2:4]), int(v[0:2]), default_hour))

    return None


def parse_relative_simple(
    text: str, *, default_hour: int = 9, reference: Optional[date] = None
) -> Optional[str]:
    """'بعد X يوم', 'بكرة', 'بعد X أسبوع', 'الأسبوع الجاي' → ISO, else None."""
    if not text:
        return None
    s = text.strip()
    ref_date = reference or datetime.now(USER_TZ).date()

    m = re.search(r"بعد\s*(\d+)\s*(?:أيام|يوم)", s)
    if m:
        return _iso_at(ref_date + timedelta(days=int(m.group(1))), default_hour)

    if re.search(r"بعد\s+يوم|بكرا|بكره|بكرة|غدا|غداً", s):
        return _iso_at(ref_date + timedelta(days=1), default_hour)

    m = re.search(r"بعد\s*(\d+)\s*(?:أسبوع|أسابيع)", s)
    if m:
        return _iso_at(ref_date + timedelta(weeks=int(m.group(1))), default_hour)

    if re.search(
        r"بعد\s+أسبوع|الأسبوع\s+الجاي|الأسبوع\s+القادم|الأسبوع\s+اللي\s+جاي", s
    ):
        return _iso_at(ref_date + timedelta(weeks=1), default_hour)

    return None


def parse_date_from_text(
    text: str, *, default_hour: int = 9, reference: Optional[date] = None
) -> Optional[str]:
    """Day name, then numeric date, then simple relative phrase."""
    if not text:
        return None
    return (
        resolve_day_name_to_iso(text, default_hour=default_hour, reference=reference)
        or parse_numeric_date(text, default_hour=default_hour)
        or parse_relative_simple(text, default_hour=default_hour, reference=reference)
    )
