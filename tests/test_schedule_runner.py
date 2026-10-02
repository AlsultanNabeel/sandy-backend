"""The sandy_schedules runner, future-self delivery in the brain's turn, the mood
entry, and the speaker gate on the brain's destructive tools."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from brain_fakes import A, B, ScriptedModel, brain_db, call, text_reply  # noqa: F401

from app.blocks import entries, schedules
from app.brain import loop, tools
from app.brain.ctx import TurnCtx
from app.features import push_tokens_store
from app.services import apns
from app.services import schedule_runner as R
from app.utils.user_profiles import active_user_profile_context

# Real time: the brain's turn reads the clock itself.
NOW = datetime.now(timezone.utc).replace(microsecond=0)


@pytest.fixture
def push(monkeypatch):
    """APNs on, one device per user; records every send."""
    sent, gone = [], []
    state = {"ok": True, "status": "ok"}
    monkeypatch.setattr(apns, "is_configured", lambda: True)
    monkeypatch.setattr(push_tokens_store, "tokens_for_user", lambda uid: [f"tok-{uid}"])
    monkeypatch.setattr(push_tokens_store, "unregister_token", lambda t, *a: gone.append(t))

    def send(token, title, body, data=None, silent=False):
        sent.append((token, body, data))
        return state["ok"], state["status"]

    monkeypatch.setattr(apns, "send", send)
    return {"sent": sent, "gone": gone, "state": state}


def _add(kind="reminder", text="دوا", minutes_ago=1, profile=A, **kw):
    with active_user_profile_context(profile):
        return schedules.add(kind, text, NOW - timedelta(minutes=minutes_ago), **kw)


def _get(sid, profile=A):
    with active_user_profile_context(profile):
        return schedules.get(sid)


def _tick(profile=A, now=NOW):
    with active_user_profile_context(profile):
        return R.run_due(profile["chat_id"], now)


# ── reminders ────────────────────────────────────────────────────────────────

def test_a_reminder_fires_once(brain_db, push):  # noqa: F811
    sid = _add()
    assert _tick() == {"fired": 1, "failed": 0}
    assert _tick() == {"fired": 0, "failed": 0}
    row = _get(sid)
    assert row["status"] == "sent" and row["fired_at"]
    assert push["sent"] == [("tok-userA", "دوا", {"kind": "reminder", "schedule_id": sid})]


def test_the_claim_is_won_once(brain_db):  # noqa: F811
    sid = _add()
    with active_user_profile_context(A):
        coll = R._base.coll(R._base.SCHEDULES)
        doc = coll.find_one({"_id": sid})
        assert R._claim(coll, doc, NOW)[0] is True
        assert R._claim(coll, doc, NOW)[0] is False


def test_a_future_reminder_waits(brain_db, push):  # noqa: F811
    sid = _add(minutes_ago=-10)
    assert _tick() == {"fired": 0, "failed": 0}
    assert _get(sid)["status"] == "pending" and push["sent"] == []


def test_a_recurring_reminder_advances_to_its_next_time(brain_db, push):  # noqa: F811
    sid = _add(recurrence="FREQ=DAILY")
    assert _tick()["fired"] == 1
    row = _get(sid)
    assert row["status"] == "pending"
    assert row["fire_at"].replace(tzinfo=timezone.utc) == NOW - timedelta(minutes=1) + timedelta(days=1)
    # Not due again until tomorrow.
    assert _tick(now=NOW + timedelta(hours=1))["fired"] == 0
    assert _tick(now=NOW + timedelta(days=1))["fired"] == 1
    assert len(push["sent"]) == 2


def test_a_recurrence_that_ended_is_sent(brain_db, push):  # noqa: F811
    sid = _add(recurrence="FREQ=DAILY;COUNT=1")
    _tick()
    assert _get(sid)["status"] == "sent"


def test_without_apns_a_reminder_is_settled_and_nothing_is_pushed(brain_db, monkeypatch):  # noqa: F811
    monkeypatch.setattr(apns, "send", lambda *a, **k: pytest.fail("pushed"))
    sid = _add()
    assert _tick()["fired"] == 1 and _get(sid)["status"] == "sent"


def test_a_stale_reminder_is_settled_without_a_push(brain_db, push):  # noqa: F811
    sid = _add(minutes_ago=R.LOOKBACK_MIN + 5)
    assert _tick()["fired"] == 1
    assert _get(sid)["status"] == "sent" and push["sent"] == []


def test_a_push_nobody_took_is_marked_failed(brain_db, push):  # noqa: F811
    push["state"].update(ok=False, status="gone")
    sid = _add()
    assert _tick() == {"fired": 0, "failed": 1}
    row = _get(sid)
    assert row["status"] == "failed" and row["last_error"]
    assert push["gone"] == ["tok-userA"]
    assert _tick() == {"fired": 0, "failed": 0}


def test_a_failed_recurring_push_stays_armed(brain_db, push):  # noqa: F811
    push["state"].update(ok=False, status="http_500")
    sid = _add(recurrence="FREQ=DAILY")
    _tick()
    row = _get(sid)
    assert row["status"] == "pending" and row["last_error"]


def test_a_crash_while_firing_is_marked_failed(brain_db, monkeypatch):  # noqa: F811
    monkeypatch.setattr(R, "_fire", lambda *a: 1 / 0)
    sid = _add()
    assert _tick() == {"fired": 0, "failed": 1}
    assert _get(sid)["status"] == "failed"


# ── nudges ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", ["daily_nudge", "summary_nudge"])
def test_a_nudge_is_push_text(brain_db, push, kind):  # noqa: F811
    sid = _add(kind, "صباح الخير")
    assert _tick()["fired"] == 1
    assert _get(sid)["status"] == "sent" and push["sent"][0][1] == "صباح الخير"


def test_a_nudge_without_apns_or_devices_fails(brain_db, monkeypatch):  # noqa: F811
    sid = _add("daily_nudge", "صباح")
    _tick()
    assert _get(sid)["status"] == "failed"
    monkeypatch.setattr(apns, "is_configured", lambda: True)
    monkeypatch.setattr(push_tokens_store, "tokens_for_user", lambda uid: [])
    sid = _add("summary_nudge", "ملخص")
    _tick()
    assert _get(sid)["status"] == "failed"


# ── scenes ───────────────────────────────────────────────────────────────────

def test_a_scene_revert_is_applied_through_the_scene_actuator(brain_db, monkeypatch):  # noqa: F811
    from app.features import scene_store
    applied = []
    monkeypatch.setattr(scene_store, "_actuate",
                        lambda actions: applied.extend(actions) or (1, []))
    sid = _add("scene", "light → on", payload={"device": "light", "value": "on"})
    assert _tick()["fired"] == 1
    assert applied == [{"device": "light", "value": "on"}]
    assert _get(sid)["status"] == "sent"


def test_a_missed_scene_retries_then_fails(brain_db, monkeypatch):  # noqa: F811
    from app.features import scene_store
    monkeypatch.setattr(scene_store, "_actuate", lambda actions: (0, ["light"]))
    sid = _add("scene", "light → on", payload={"device": "light", "value": "on"})
    now = NOW
    for attempt in range(1, scene_store.MAX_TIMER_TRIES):
        _tick(now=now)
        row = _get(sid)
        assert row["status"] == "pending" and row["payload"]["tries"] == attempt
        now = now + timedelta(minutes=1)
    _tick(now=now)
    assert _get(sid)["status"] == "failed"


# ── migrated rows, and what the runner leaves alone ─────────────────────────

def test_a_migrated_row_on_time_fires_like_any_other(brain_db, push):  # noqa: F811
    sid = _add(migrated_from={"collection": "sandy_reminders", "id": "r1"})
    assert _tick() == {"fired": 1, "failed": 0}
    assert _get(sid)["status"] == "sent" and len(push["sent"]) == 1


def test_a_late_migrated_row_is_settled_without_firing_again(brain_db, monkeypatch):  # noqa: F811
    """Its old store already fired it: a scene revert replayed hours later would
    switch someone's lights for no reason."""
    from app.features import scene_store
    applied = []
    monkeypatch.setattr(scene_store, "_actuate",
                        lambda actions: applied.extend(actions) or (1, []))
    sid = _add("scene", "light → off", minutes_ago=R.LOOKBACK_MIN + 60,
               payload={"device": "light", "value": "off"},
               migrated_from={"collection": "sandy_scene_timers", "id": "t1"})
    assert _tick() == {"fired": 1, "failed": 0}
    assert _get(sid)["status"] == "sent" and applied == []


def test_future_self_messages_and_cancelled_rows_are_not_fired(brain_db, push):  # noqa: F811
    future = _add("message_to_future_self", "إلك")
    cancelled = _add(status="cancelled")
    assert _tick() == {"fired": 0, "failed": 0}
    assert R.users_with_due(brain_db, NOW) == []
    assert [_get(s)["status"] for s in (future, cancelled)] == ["pending", "cancelled"]
    assert push["sent"] == []


def test_the_tick_runs_each_tenant_in_its_own_scope(brain_db, push):  # noqa: F811
    a, b = _add(text="أ"), _add(text="ب", profile=B)
    assert sorted(R.users_with_due(brain_db)) == ["userA", "userB"]
    assert R.run_all_due(brain_db) == 2
    assert _get(a)["status"] == "sent" and _get(b, B)["status"] == "sent"
    assert sorted((t, body) for t, body, _ in push["sent"]) == [("tok-userA", "أ"), ("tok-userB", "ب")]


# ── future self, in the brain's turn ─────────────────────────────────────────

def _turn(model, message="شو الأخبار"):
    with active_user_profile_context(A):
        return loop.run_turn(message, user_id="userA", chat_id="userA", source="web",
                             complete=model)


def test_a_future_message_is_delivered_into_the_next_reply_once(brain_db):  # noqa: F811
    sid = _add("message_to_future_self", "لا تنسى تتصل بأمك")
    later = _add("message_to_future_self", "بعدين", minutes_ago=-60 * 24)
    first = ScriptedModel(text_reply("أهلين"))
    _turn(first)
    assert "لا تنسى تتصل بأمك" in first.seen[0][0]["content"]
    assert "بعدين" not in first.seen[0][0]["content"]
    row = _get(sid)
    assert row["status"] == "sent" and row["payload"]["delivered_at"]
    second = ScriptedModel(text_reply("أهلين"))
    _turn(second)
    assert "لا تنسى تتصل بأمك" not in second.seen[0][0]["content"]
    assert _get(later)["status"] == "pending"


def test_a_failed_turn_delivers_nothing(brain_db):  # noqa: F811
    sid = _add("message_to_future_self", "رسالة")
    state = _turn(lambda *a, **k: None)
    assert state["error"]
    assert _get(sid)["status"] == "pending"


def test_another_tenants_message_never_reaches_this_turn(brain_db):  # noqa: F811
    _add("message_to_future_self", "سر ب", profile=B)
    model = ScriptedModel(text_reply("أهلين"))
    _turn(model)
    assert "سر ب" not in model.seen[0][0]["content"]


# ── mood entry (the old emotional moment) ────────────────────────────────────

def test_a_mood_is_the_users_words_sealed_once_per_turn(brain_db, monkeypatch):  # noqa: F811
    from cryptography.fernet import Fernet

    from app.utils import ltm_crypto
    monkeypatch.setattr(ltm_crypto, "_fernet", Fernet(Fernet.generate_key()))
    monkeypatch.setattr(ltm_crypto, "_init_attempted", True)
    monkeypatch.setattr(entries, "embed_text", lambda t: pytest.fail("embedded a mood"))
    ctx = TurnCtx(user_id="userA", message="اليوم كان صعب كثير بالشغل")
    with active_user_profile_context(A):
        first = tools.execute("remember", {"kind": "mood", "text": "متوتر",
                                           "data": {"mood": "stressed"}}, ctx)
        again = tools.execute("remember", {"kind": "mood", "text": "متوتر",
                                           "data": {"mood": "sad"}}, ctx)
        rows = entries.list_entries("mood")
    assert first["ok"] and again["id"] == first["id"] and len(rows) == 1
    assert rows[0]["data"] == {"mood": "stressed", "encrypted": True}
    assert ltm_crypto.decrypt_field(rows[0]["text"]) == "اليوم كان صعب كثير بالشغل"


@pytest.mark.parametrize("data", [{}, {"mood": "neutral"}, {"mood": "bored"}])
def test_a_mood_the_old_turn_would_not_keep_is_refused(brain_db, data):  # noqa: F811
    with active_user_profile_context(A):
        out = tools.execute("remember", {"kind": "mood", "text": "x", "data": data},
                            TurnCtx(user_id="userA", message="x"))
        assert out["ok"] is False and entries.list_entries("mood") == []


def test_the_turn_writes_a_mood_when_the_model_records_one(brain_db):  # noqa: F811
    from brain_fakes import tools_reply
    model = ScriptedModel(tools_reply(call("remember", kind="mood", text="زعلان",
                                           data={"mood": "sad"})),
                          text_reply("سلامتك"))
    _turn(model, "زعلان كثير اليوم")
    with active_user_profile_context(A):
        (row,) = entries.list_entries("mood")
    assert row["data"]["mood"] == "sad" and row["source"] == "chat"
    assert "mood" in model.seen[0][0]["content"]


# ── speaker gate on the brain's tools ────────────────────────────────────────

@pytest.mark.parametrize("name, args, sensitive", [
    ("list_update", {"match_text": "حليب", "delete": True}, True),
    ("list_update", {"match_text": "حليب", "all_matching": True, "done": True}, True),
    ("list_update", {"match_text": "حليب", "done": True}, False),
    ("schedule_update", {"match_text": "دوا", "cancel": True}, True),
    ("schedule_update", {"match_text": "دوا", "all_matching": True, "when": "بكرا"}, True),
    ("schedule_update", {"match_text": "دوا", "when": "بكرا"}, False),
    ("schedule", {"kind": "message_to_future_self", "text": "x", "when": "بكرا"}, True),
    ("schedule", {"kind": "reminder", "text": "x", "when": "بكرا"}, False),
    ("confirm", {"answer": "اه"}, True),
    ("recall", {}, False),
    ("list_add", {"list": "shopping", "text": "x"}, False),
])
def test_the_speaker_gate_covers_the_brains_destructive_calls(name, args, sensitive):
    from app.api.voice_ws.speaker import _is_sensitive_call
    assert _is_sensitive_call(name, args) is sensitive


def test_the_voice_loop_asks_the_gate_with_the_call_args():
    import inspect

    from app.api.voice_ws import session
    src = inspect.getsource(session)
    assert "gate_on and _is_sensitive_call(fc.name, dict(fc.args or {}))" in src
