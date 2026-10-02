"""Times read right: a named day, a day of the month, noon, «مع», reminders tied to a
meeting, repeats, a snooze after it rang, a due taken off, calendar periods, each
user's own clock."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from brain_fakes import A, brain_db  # noqa: F401

from app.blocks import items, schedules
from app.brain import tools
from app.brain import when as W
from app.brain.ctx import TurnCtx
from app.utils import time as T
from app.utils.time import USER_TZ
from app.utils.user_profiles import active_user_profile_context

SAT_10AM = datetime(2026, 10, 3, 10, 0, tzinfo=USER_TZ)


def _local(text, now=SAT_10AM):
    at = W._clock(text, now)
    return at.astimezone(USER_TZ).strftime("%Y-%m-%d %H:%M") if at else None


@pytest.mark.parametrize("text,want", [
    ("الجمعة الساعة 5", "2026-10-09 17:00"),          # the day named, not the nearest five
    ("يوم 15 الساعة 5", "2026-10-15 17:00"),          # 15 is the day, 5 the hour
    ("15 بالشهر الساعة 9", "2026-10-15 09:00"),
    ("يوم 2 الساعة 9 الصبح", "2026-11-02 09:00"),     # the 2nd has passed: next month
    ("الساعة 12 الظهر", "2026-10-03 12:00"),          # noon, not midnight
    ("12 بالليل", "2026-10-04 00:00"),
    ("بكرا 9 مع الدكتور", "2026-10-04 09:00"),        # «مع» is not «مساءً»
    ("الساعة 5 بالصالة", "2026-10-03 17:00"),         # nor is a word starting with ص «صباحاً»
    ("السبت الساعة 11", "2026-10-03 11:00"),          # today's name, still ahead
    ("السبت الساعة 9 الصبح", "2026-10-10 09:00"),     # today's name, gone: next week
    ("اليوم 5", "2026-10-03 17:00"),
])
def test_clock_words(text, want):
    assert _local(text) == want


def test_periods_are_the_calendar_week_month_and_year():
    tue = datetime(2026, 10, 13, 15, 0, tzinfo=USER_TZ)

    def start(p):
        return W.period_range(p, tue)[0].astimezone(USER_TZ).date().isoformat()

    assert start("week") == "2026-10-11"       # from Sunday
    assert start("month") == "2026-10-01"
    assert start("year") == "2026-01-01"


@pytest.fixture
def tenant(brain_db):  # noqa: F811
    T._cache.clear()
    with active_user_profile_context(A):
        yield brain_db
    T._cache.clear()


def _run(name, **args):
    ctx = TurnCtx(user_id="userA")
    ctx.confirmed = True
    return tools.execute(name, args, ctx)


def test_a_reminder_before_an_existing_meeting(tenant):
    meeting = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=3)
    mid = schedules.add("reminder", "الاجتماع", meeting)
    out = _run("schedule", kind="reminder", text="جهّز للاجتماع", before_id=mid, before_minutes=15)
    assert out["ok"]
    assert W.aware_utc(schedules.get(out["id"])["fire_at"]) == meeting - timedelta(minutes=15)


def test_repeat_changed_stopped_and_one_skipped(tenant):
    first = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=2)
    sid = schedules.add("reminder", "الدوا", first, recurrence="FREQ=DAILY")
    assert _run("schedule_update", id=sid, skip_next=True)["ok"]
    assert W.aware_utc(schedules.get(sid)["fire_at"]) == first + timedelta(days=1)
    assert _run("schedule_update", id=sid, recurrence="weekly")["ok"]
    assert schedules.get(sid)["recurrence"] == "FREQ=WEEKLY"
    assert _run("schedule_update", id=sid, stop_repeat=True)["ok"]
    assert schedules.get(sid)["recurrence"] == ""


def test_snooze_a_one_time_reminder_that_just_rang(tenant):
    now = datetime.now(timezone.utc)
    sid = schedules.add("reminder", "المي", now + timedelta(minutes=1))
    schedules.update(sid, status="sent")
    tenant["sandy_schedules"].update_one({"_id": sid}, {"$set": {"fired_at": now}})
    from app.brain import context
    assert f"#{sid}" in context.state_block()
    assert _run("schedule_update", id=sid, shift_minutes=15)["ok"]
    row = schedules.get(sid)
    assert row["status"] == "pending" and W.aware_utc(row["fire_at"]) > now + timedelta(minutes=14)


def test_snooze_a_repeating_one_leaves_the_series(tenant):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    sid = schedules.add("reminder", "الرياضة", now + timedelta(days=1), recurrence="FREQ=DAILY")
    tenant["sandy_schedules"].update_one({"_id": sid}, {"$set": {"fired_at": now}})
    assert _run("schedule_update", id=sid, shift_minutes=15)["ok"]
    assert W.aware_utc(schedules.get(sid)["fire_at"]) == now + timedelta(days=1)
    snoozes = [s for s in schedules.list_schedules("reminder", status="pending") if s["id"] != sid]
    assert len(snoozes) == 1 and snoozes[0]["text"] == "الرياضة"


def test_a_due_is_taken_off_a_task(tenant):
    iid = items.add("tasks", "التقرير", due=datetime.now(timezone.utc) + timedelta(days=1))
    assert _run("list_update", id=iid, no_due=True)["ok"]
    assert items.get(iid).get("due") is None


def test_each_user_reads_their_own_clock(tenant):
    tenant["sandy_users"].insert_one({"_id": "userA"})
    T.note_zone("userA", "America/New_York")
    assert T.zone_name() == "America/New_York"
    assert tenant["sandy_users"].find_one({"_id": "userA"})["timezone"] == "America/New_York"
    noon_utc = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
    assert noon_utc.astimezone(USER_TZ).hour == noon_utc.astimezone(ZoneInfo("America/New_York")).hour
    T.note_zone("userA", "Not/AZone")                     # nonsense is ignored
    assert T.zone_name() == "America/New_York"
    with active_user_profile_context({"chat_id": "userB", "relation": "user"}):
        assert T.zone_name() == T.DEFAULT_ZONE


def test_a_signed_in_call_sends_the_phones_zone(tenant, monkeypatch):
    from flask import Flask, jsonify

    from app.api.auth_handlers import make_token, require_auth

    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    tenant["sandy_users"].insert_one({"_id": "userA"})
    app = Flask(__name__)

    @app.route("/ping")
    @require_auth
    def ping(claims):
        return jsonify(ok=True)

    token = make_token("user", "userA")
    app.test_client().get("/ping", headers={"Authorization": f"Bearer {token}",
                                            "X-Timezone": "Asia/Dubai"})
    assert tenant["sandy_users"].find_one({"_id": "userA"})["timezone"] == "Asia/Dubai"
