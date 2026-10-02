"""Devices as asked: a question is not an order, state is read, a command waits for
its time, a room or several at once, a relative level, a plain «it did not work»;
voice gets every field and can answer «which one?»."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from brain_fakes import A, brain_db  # noqa: F401

from app.blocks import items, schedules
from app.brain import tools, voice
from app.brain.ctx import TurnCtx
from app.features import device_store, scene_store
from app.utils.user_profiles import active_user_profile_context


class _Room:
    def __init__(self, up=True):
        self.up, self.sent = up, []

    def send_to_topic(self, topic, payload):
        self.sent.append((topic, payload))
        return self.up


@pytest.fixture
def room(brain_db, monkeypatch):  # noqa: F811
    client = _Room()
    monkeypatch.setattr("app.integrations.room_device.get_room_device_client", lambda: client)
    with active_user_profile_context(A):
        device_store.add_device("lamp", "ضو الصالة", "dimmer", {"kind": "mqtt", "topic": "room/cmd/lamp"},
                                room="الصالة")
        device_store.add_device("kitchen", "ضو المطبخ", "switch", {"kind": "mqtt", "topic": "room/cmd/kitchen"},
                                room="المطبخ")
        device_store.add_device("ac", "المكيف", "switch", {"kind": "mqtt", "topic": "room/cmd/ac"},
                                room="الصالة")
        yield client


def _run(name, **args):
    return tools.execute(name, args, TurnCtx(user_id="userA"))


def test_state_is_read_not_changed(room):
    device_store.set_state("lamp", "60")
    out = _run("device_state", device="ضو الصالة")
    assert out["devices"][0]["state"] == "60" and room.sent == []
    assert len(_run("device_state")["devices"]) == 3


def test_a_device_command_waits_for_its_time_and_a_scene_leaves_it(room):
    out = _run("schedule", kind="reminder", text="طفي المكيف", in_minutes=60, device="المكيف", value="off")
    assert out["ok"] and "بعمل" in out["reply"]
    row = schedules.get(out["id"])
    assert row["kind"] == "scene" and row["payload"] == {"device": "ac", "value": "off", "asked": True}
    scene_store.add_scene("calm", actions=[{"device": "lamp", "value": "20"}])
    scene_store.apply_scene("calm")
    assert schedules.get(out["id"])["status"] == "pending"
    # His to see and cancel, like a reminder.
    assert _run("schedule_update", id=out["id"], cancel=True).get("needs_confirmation")


def test_a_room_or_several_at_once(room):
    out = _run("device_control", room="الصالة", action="off")
    assert out["ok"] and {t for t, _ in room.sent} == {"room/cmd/lamp", "room/cmd/ac"}
    room.sent.clear()
    _run("device_control", devices=["ضو الصالة", "ضو المطبخ"], action="off")
    assert {t for t, _ in room.sent} == {"room/cmd/lamp", "room/cmd/kitchen"}


def test_dim_a_little_from_where_it_is(room):
    device_store.set_state("lamp", "70")
    _run("device_control", device="lamp", action="set", by=-20)
    assert room.sent[-1] == ("room/cmd/lamp", "50")
    device_store.set_state("lamp", "on")
    _run("device_control", device="lamp", action="set", by=20)
    assert room.sent[-1] == ("room/cmd/lamp", "100")


def test_an_offline_device_says_it_did_not_work(room):
    room.up = False
    out = _run("device_control", device="المكيف", action="on")
    assert out["ok"] is False and out["reply"].startswith("ما اشتغل")
    assert "شغّلت" not in out["reply"]


def test_voice_gets_the_fields_named():
    by_name = {d["name"]: d for d in tools.declarations()}
    remember = by_name["remember"]["parameters"]["properties"]
    assert {"amount", "category", "mood"} <= set(remember["data"]["properties"])
    add = by_name["list_add"]["parameters"]["properties"]
    assert {"days", "time", "repeat", "qty"} <= set(add["data"]["properties"])


def test_voice_asks_which_one_and_takes_the_answer(brain_db):  # noqa: F811
    with active_user_profile_context(A):
        a = items.add("tasks", "أشتري حليب")
        b = items.add("tasks", "أشتري حليب")
        out = voice.dispatch("list_update", {"list": "tasks", "match_text": "حليب", "done": True}, "userA")
        assert "١." in out["reply"] and "ok" not in out
        out = voice.dispatch("confirm", {"answer": "الأولى"}, "userA")
        assert items.get(a)["done"] and not items.get(b)["done"]
        out = voice.dispatch("list_update", {"list": "tasks", "match_text": "حليب", "delete": True}, "userA")
        assert "متأكد" in out["reply"]           # one left: no choice, only the yes
        assert voice.dispatch("confirm", {"answer": "اه"}, "userA")["ok"]
        assert items.get(b) is None


def test_a_scene_with_the_room_offline_says_so(room):
    room.up = False
    scene_store.add_scene("calm", actions=[{"device": "lamp", "value": "20"}])
    out = tools.execute("scene_apply", {"name": "calm"}, TurnCtx(user_id="userA"))
    assert out["ok"] is False and out["reply"].startswith("ما تطبّق")


def test_device_timers_show_in_the_state(room):
    from app.brain import context
    later = datetime.now(timezone.utc) + timedelta(hours=1)
    sid = schedules.add("scene", "المكيف → off", later, {"device": "ac", "value": "off", "asked": True})
    block = context.state_block()
    assert f"#{sid}" in block and "أجهزته:" in block and "المكيف (ac، الصالة)" in block
