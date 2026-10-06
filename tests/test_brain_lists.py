"""Lists and reminders as the user means them: a habit ticked for today, a guess that
asks, «كمان حليب», moves and details, reminders only, a long list, totals, what rang,
and the weather where they live."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from brain_fakes import A, brain_db  # noqa: F401

from app.blocks import entries, items, schedules
from app.brain import context, tools
from app.brain.ctx import TurnCtx
from app.utils import time as T
from app.utils.user_profiles import active_user_profile_context


@pytest.fixture
def tenant(brain_db):  # noqa: F811
    T._cache.clear()
    with active_user_profile_context(A):
        yield brain_db
    T._cache.clear()


def _run(name, confirmed=False, **args):
    ctx = TurnCtx(user_id="userA")
    ctx.confirmed = confirmed
    return tools.execute(name, args, ctx)


def test_done_on_a_habit_ticks_today_and_keeps_the_habit(tenant):
    gym = items.add("habits", "الجيم")
    assert _run("list_update", id=gym, done=True)["ok"]
    assert not items.get(gym)["done"]
    kept = entries.list_entries("habit")
    assert len(kept) == 1 and kept[0]["data"]["habit_item_id"] == gym
    assert "أصلاً" in _run("list_update", id=gym, done=True)["reply"]
    assert len(entries.list_entries("habit")) == 1      # once a day


def test_a_near_spelling_asks_before_it_acts(tenant):
    net = items.add("tasks", "دفع فاتورة النت")
    out = _run("list_update", match_text="دفع فاتورة المي", done=True)
    assert out.get("needs_confirmation") and "أقرب إشي" in out["summary"]
    assert not items.get(net)["done"]


def test_more_of_the_same_adds_to_its_quantity_and_a_new_time_moves_it(tenant):
    milk = items.add("shopping", "حليب")
    out = _run("list_add", list="shopping", text="حليب", qty=1)
    assert out["updated"] and items.get(milk)["data"]["qty"] == 2
    task = items.add("tasks", "التقرير")
    soon = (datetime.now() + timedelta(days=30)).replace(hour=10, minute=0, second=0, microsecond=0)
    _run("list_add", list="tasks", text="التقرير", due=soon.isoformat())
    assert items.get(task)["due"] is not None
    assert len(items.list_items("tasks")) == 1
    assert _run("list_add", list="tasks", text="التقرير")["already"]


def test_an_item_gets_its_priority_details_and_a_new_list(tenant):
    gym = items.add("habits", "الجيم")
    _run("list_update", id=gym, priority="high", data={"days": [1, 3], "time": "07:00"})
    row = items.get(gym)
    assert row["priority"] == "high" and row["data"] == {"days": [1, 3], "time": "07:00"}
    idea = items.add("tasks", "تطبيق للطبخ")
    _run("list_update", id=idea, move_to="plans")
    assert items.get(idea)["list"] == "plans"


def test_cancel_a_reminder_reaches_reminders_only_and_a_sealed_message_stays_sealed(tenant):
    later = datetime.now(timezone.utc) + timedelta(days=3)
    schedules.add("message_to_future_self", "سر بيني وبينك", later)
    schedules.add("scene", "light → off", later)
    out = _run("schedule_update", match_text="سر بيني وبينك", cancel=True)
    assert out["ok"] is False
    rows = _run("recall", query="")["rows"]
    texts = [r["text"] for r in rows]
    assert "سر بيني وبينك" not in texts and "light → off" not in texts
    assert "(رسالة مختومة لحد موعدها)" in texts


def test_a_long_list_still_shows_the_newest_and_the_soonest(tenant):
    old = datetime.now(timezone.utc) - timedelta(days=10)
    for n in range(60):
        items.add("tasks", f"مهمة قديمة {n}", created_at=old + timedelta(minutes=n))
    soon = items.add("tasks", "موعد قريب", due=datetime.now(timezone.utc) + timedelta(hours=2),
                     created_at=old - timedelta(days=1))
    newest = items.add("tasks", "أحدث مهمة")
    block = context.state_block()
    assert f"#{soon}" in block and f"#{newest}" in block


def test_spending_comes_back_summed(tenant):
    for n in range(40):
        entries.add("expense", f"قهوة {n}", {"amount": 5, "category": "food"})
    entries.add("expense", "مواصلات", {"amount": 20, "category": "transport"})
    out = _run("recall", kind="expense")
    assert out["spending"]["total"] == 220 and out["spending"]["count"] == 41
    assert out["spending"]["by_category"] == {"food": 200, "transport": 20}


def test_reminders_that_rang_are_found(tenant):
    now = datetime.now(timezone.utc)
    sid = schedules.add("reminder", "الدوا", now + timedelta(minutes=1))
    schedules.update(sid, status="sent")
    tenant["sandy_schedules"].update_one({"_id": sid}, {"$set": {"fired_at": now - timedelta(hours=3)}})
    schedules.add("reminder", "بكرا", now + timedelta(days=1))
    out = _run("recall", rang=True)
    assert [r["text"] for r in out["rows"]] == ["الدوا"] and out["rows"][0]["rang_at"]


def test_weather_with_no_city_is_where_they_live(tenant, monkeypatch):
    from app.features import weather

    asked = []
    monkeypatch.setattr(weather, "get_weather", lambda city: asked.append(city) or {"x": 1})
    monkeypatch.setattr(weather, "format_weather_for_prompt", lambda d: "مشمس")
    tenant["sandy_users"].insert_one({"_id": "userA", "city": "Ramallah"})
    assert _run("weather")["ok"] and asked == ["Ramallah"]
    # No saved city: no guessed or default one (it was Egypt's for everyone); she asks.
    tenant["sandy_users"].update_one({"_id": "userA"}, {"$unset": {"city": ""}})
    T.note_zone("userA", "Asia/Amman")
    out = _run("weather")
    assert not out["ok"] and "مدينة" in out["reply"]
    assert asked == ["Ramallah"]


def test_a_city_is_looked_up_as_itself_not_in_egypt(monkeypatch):
    from app.features import weather

    urls = []
    monkeypatch.setattr(weather, "_fetch_weather", lambda url: urls.append(url) or {})
    weather._cache.clear()
    weather.get_weather("Amman")
    assert urls and "Egypt" not in urls[0] and "Amman" in urls[0]


def test_an_alarm_reminder_is_marked_and_can_be_unmarked(tenant):
    out = _run("schedule", kind="reminder", text="صحّيني", in_minutes=60, important=True)
    assert "منبه" in out["reply"]
    assert schedules.get(out["id"])["payload"] == {"important": True}      # keeps to a Focus
    loud = _run("schedule", kind="reminder", text="الطيارة", in_minutes=90, important=True, break_focus=True)
    assert schedules.get(loud["id"])["payload"] == {"important": True, "break_focus": True}
    assert "منبه" in context.state_block()
    _run("schedule_update", id=out["id"], important=False, confirmed=True)
    assert schedules.get(out["id"])["payload"]["important"] is False

