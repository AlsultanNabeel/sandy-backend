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


def test_router_and_chat_prompts_carry_the_clock():
    from app.agent.agents.fc_router import _build_user_prompt
    prompt = _build_user_prompt({"message": "ذكريني الساعة 5 العصر",
                                 "conversation_history": [_turn(timedelta(hours=1))]})
    assert "الآن:" in prompt and "ISO:" in prompt and "آخر تواصل" in prompt


def test_a_guessed_past_reminder_time_is_reparsed_from_the_words(monkeypatch):
    """The router filled remind_at_iso with a date from its training years."""
    from app.agent.executor import reminder_handlers as rh

    future = (datetime.now(USER_TZ) + timedelta(hours=3)).replace(microsecond=0)
    seen, added = {}, {}

    def fake_parse(text, create_chat_completion_fn=None, return_json=False):
        seen["text"] = text
        return {"success": True, "remind_at_iso": future.isoformat()}

    def fake_add(text, remind_at_iso, **kw):
        added["iso"] = remind_at_iso
        return {"success": True}

    monkeypatch.setattr(rh, "parse_reminder_time_ai", fake_parse)
    monkeypatch.setattr(rh, "add_reminder", fake_add)
    monkeypatch.setattr(rh, "active_profile_is_guest", lambda: False)
    out = rh.handle_reminder_action(
        {"action": "create", "text": "المحاضرة", "time_text": "الساعة 5 العصر",
         "remind_at_iso": "2024-09-20T17:00:00"},
        user_message="ذكريني الساعة 5 العصر اروح عالمحاضرة",
        normalized_user_message="ذكريني الساعة 5 العصر اروح عالمحاضرة",
        session={}, session_file=None, mongo_db=None, tasks_file=None,
        create_chat_completion_fn=lambda **k: None, save_session_fn=lambda *a, **k: None)
    assert out["ok"], out["reply"]
    assert "5" in seen["text"], "the user's own words were not parsed"
    assert datetime.fromisoformat(added["iso"]) == future
