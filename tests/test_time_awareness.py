"""Sandy knows what time it is, and how long since you last spoke."""
from datetime import datetime, timedelta, timezone

from app.utils import time_awareness as ta
from app.utils.time import USER_TZ

NOW = datetime(2026, 9, 20, 17, 5, tzinfo=USER_TZ)  # Sunday


def _turn(delta, via="الروبوت", role="user"):
    ts = (NOW - delta).astimezone(timezone.utc).isoformat()
    return {"role": role, "content": "x", "timestamp": ts, "via": via}


def test_now_line_names_day_date_time_and_iso():
    line = ta.now_line(NOW)
    assert "الأحد" in line and "20/09/2026" in line and "5:05 م" in line
    assert "2026-09-20T17:05:00" in line


def test_gap_since_last_message_uses_the_newest_turn_on_any_channel():
    hist = [_turn(timedelta(days=3), via="التطبيق"),
            _turn(timedelta(hours=2, minutes=30), via="الروبوت")]
    line = ta.last_contact_line(hist, NOW)
    assert "قبل 2 ساعة و30 دقيقة" in line and "الروبوت" in line and "اليوم" in line


def test_no_history_says_so():
    assert "ما في محادثة" in ta.last_contact_line([], NOW)


def test_long_absence_is_counted_in_days():
    assert ta.ago_ar(timedelta(days=5, hours=3)) == "قبل 5 يوم"
    assert ta.ago_ar(timedelta(seconds=30)) == "قبل لحظات"


def test_model_dates_from_another_year_are_not_trusted():
    assert not ta.plausible_future_iso("2024-05-01T17:00:00", NOW)
    assert not ta.plausible_future_iso("2031-01-01T17:00:00", NOW)
    assert not ta.plausible_future_iso("2026-09-20T09:00:00", NOW)    # earlier today
    assert ta.plausible_future_iso("2026-09-20T18:00:00", NOW)
    assert ta.plausible_future_iso("2026-09-20T00:00:00", NOW)        # "today", date only
    assert not ta.plausible_future_iso("garbage", NOW)
