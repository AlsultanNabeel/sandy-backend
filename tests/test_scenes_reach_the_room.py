"""A scene reaches the room it was written for.

Audit F7: the built-ins and the app's scene editor wrote the old room words («light»,
«music», «fan», «curtain», «color»), and applying looked a device up by that literal name.
The real devices are the room light (a switch: a servo pressing the wall switch) and the
room music (a list with no on/off), so every scene — «morning», «sleep», the focus scene —
sent nothing, and Sandy said the room was not connected while it was. Even by the right
name, the values (a level for the light, «on» for the music) were refused.
"""
from __future__ import annotations

from brain_fakes import B, brain_db  # noqa: F401 — fixture
from test_devices_know_their_board import NODE, broker, robot  # noqa: F401 — fixtures

from app.brain import tools
from app.brain.ctx import TurnCtx
from app.features import device_store, scene_store
from app.utils.user_profiles import active_user_profile_context


def _apply(name):
    return tools.execute("scene_apply", {"name": name}, TurnCtx(user_id="userA"))


def test_morning_presses_the_room_light_and_plays_the_music(robot, broker):  # noqa: F811
    out = _apply("morning")
    assert (f"sandy/node/{NODE}/room/light", "on") in broker.sent
    assert (f"sandy/node/{NODE}/room/music", "resume") in broker.sent
    assert device_store.get_device("room_light")["state"] == "on"
    # The curtain is no device of his: passed over, and said so.
    assert "الستارة" in out["reply"] and "تخطّيتها" in out["reply"]


def test_sleep_turns_off_and_stops(robot, broker):  # noqa: F811
    out = _apply("sleep")
    assert (f"sandy/node/{NODE}/room/light", "off") in broker.sent
    assert (f"sandy/node/{NODE}/room/music", "stop") in broker.sent
    assert "المروحة" in out["reply"] and "الستارة" in out["reply"]


def test_a_level_on_the_light_is_on_or_off(robot, broker):  # noqa: F811
    r = scene_store._actuate([{"device": "light", "value": "0"}])
    assert r["sent"] == 1 and broker.sent == [(f"sandy/node/{NODE}/room/light", "off")]


def test_the_editor_is_shown_the_real_devices(robot):  # noqa: F811
    morning = next(s for s in scene_store.list_scenes() if s["name"] == "morning")
    assert {"device": "room_light", "value": "on"} in morning["actions"]
    assert {"device": "room_music", "value": "resume"} in morning["actions"]
    # A word no device of his answers to stays as it was written.
    assert {"device": "curtain", "value": "open"} in morning["actions"]


def test_two_rooms_are_not_guessed(robot, broker):  # noqa: F811
    """Two robots with a room each: «the light» names neither, and the wrong light going
    off in the wrong room is a silent failure."""
    robot["sandy_nodes"].insert_one({"node_id": "9999", "user_id": "userA", "outputs": [],
                                     "telemetry": {"room_online": True}})
    device_store.add_device("room_light_2", "ضو التاني", "switch",
                            {"kind": "node", "node_id": "9999", "output": "room/light"})
    r = scene_store._actuate([{"device": "light", "value": "on"}])
    assert r["sent"] == 0 and r["skipped"] == ["ضو الغرفة"] and broker.sent == []


def test_with_no_room_at_all_the_words_are_named_not_the_room_offline(robot, broker):  # noqa: F811
    with active_user_profile_context(B):
        out = tools.execute("scene_apply", {"name": "off"}, TurnCtx(user_id="userB"))
    assert out["ok"] is False and broker.sent == []
    assert "ضو الغرفة" in out["reply"] and "مش متّصل" not in out["reply"]


def test_the_app_is_told_what_was_passed_over(robot, broker, monkeypatch):  # noqa: F811
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    from app.api.auth_handlers import make_token
    from app.api.server import create_app

    c = create_app(mongo_db=robot).test_client()
    r = c.post("/api/life/scenes/apply", json={"name": "morning"},
               headers={"Authorization": f"Bearer {make_token('user', 'userA')}"})
    body = r.get_json()
    assert r.status_code == 200 and body["online"] is True and body["skipped"] == ["الستارة"]
