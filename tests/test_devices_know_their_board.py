"""A device is as connected as the board behind it.

Audit F10: `online` was written once, False, when the device was made, so every card in
the app said «not connected» and Sandy answered «is the light on?» with «not connected»
while it answered. Nothing wrote it on the device, so it is read from the board now.
"""
from __future__ import annotations

import json

import pytest
from brain_fakes import A, brain_db  # noqa: F401 — fixture

from app.features import device_store
from app.integrations import mqtt_ingest
from app.utils.user_profiles import active_user_profile_context

NODE = "8421"


def _beat(topic: str, body: dict) -> None:
    mqtt_ingest._handle_message(f"sandy/node/{NODE}/{topic}", json.dumps(body).encode())


def brain_beat(**fields) -> None:
    _beat("status", {"online": True,
                     "outputs": [{"id": "volume", "kind": "audio"},
                                 {"id": "mic_l", "kind": "audio"},
                                 {"id": "mic_l_gain", "kind": "audio"}],
                     **fields})


def room_beat() -> None:
    _beat("room/status", {"online": True,
                          "outputs": [{"id": "light", "kind": "servo"},
                                      {"id": "music", "kind": "audio"}]})


@pytest.fixture
def robot(brain_db):  # noqa: F811
    brain_db["sandy_nodes"].insert_one({"node_id": NODE, "user_id": "userA", "label": "ساندي",
                                        "outputs": [], "telemetry": {}})
    brain_beat(volume=70)
    room_beat()
    with active_user_profile_context(A):
        yield brain_db


def _online() -> dict:
    return {d["name"]: d["online"] for d in device_store.list_devices()}


def test_a_device_whose_board_answers_is_connected(robot):
    on = _online()
    assert on["sandy_volume"] and on["room_light"] and on["room_music"]
    assert device_store.get_device("room_light")["online"]


def test_the_room_going_leaves_the_brain_connected(robot):
    _beat("room/status", {"online": False})          # the room node's MQTT will
    on = _online()
    assert not on["room_light"] and not on["room_music"]
    assert on["sandy_volume"]


def test_the_brain_going_or_in_safe_mode_is_not_connected(robot):
    brain_beat(safe=True)
    assert not _online()["sandy_volume"]
    _beat("status", {"online": False})               # the brain's MQTT will
    assert not _online()["sandy_volume"]
    assert _online()["room_light"]


def test_sandy_reads_it_too(robot):
    from app.brain import tools
    from app.brain.ctx import TurnCtx

    rows = tools.execute("device_state", {"device": "room_light"}, TurnCtx(user_id="userA"))
    assert rows["devices"][0]["connected"] is True


# Audit F18: «sent» meant only that the broker took it. A board whose MQTT will had come
# was sent the command, which the broker dropped, and Sandy said «done».

class _Broker:
    def __init__(self):
        self.sent = []

    def send_to_topic(self, topic, payload):
        self.sent.append((topic, payload))
        return True


@pytest.fixture
def broker(robot, monkeypatch):
    b = _Broker()
    monkeypatch.setattr("app.integrations.room_device.get_room_device_client", lambda: b)
    return b


def test_a_gone_board_is_not_sent_and_she_says_not_connected(robot, broker):
    from app.brain import tools
    from app.brain.ctx import TurnCtx

    device_store.set_state("room_light", "off")
    _beat("room/status", {"online": False})
    out = tools.execute("device_control", {"device": "room_light", "action": "on"},
                        TurnCtx(user_id="userA"))
    assert out["ok"] is False and "مش متّصل" in out["reply"]
    assert not out["reply"].startswith("ما اشتغل")      # not «it did not work, try again»
    assert broker.sent == []
    assert device_store.get_device("room_light")["state"] == "off"


def test_a_scene_goes_on_without_the_gone_board_and_names_it(robot, broker):
    from app.brain import tools
    from app.brain.ctx import TurnCtx
    from app.features import scene_store

    scene_store.add_scene("evening", actions=[{"device": "sandy_volume", "value": "30"},
                                              {"device": "room_light", "value": "on"}])
    _beat("room/status", {"online": False})
    out = tools.execute("scene_apply", {"name": "evening"}, TurnCtx(user_id="userA"))
    assert broker.sent == [(f"sandy/node/{NODE}/volume", "30")]
    assert "ضوء الغرفة" in out["reply"] and "تخطّيته" in out["reply"]


def test_the_app_is_told_not_connected_apart_from_not_reached(robot, broker, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    from app.api.auth_handlers import make_token
    from app.api.server import create_app

    c = create_app(mongo_db=robot).test_client()
    h = {"Authorization": f"Bearer {make_token('user', 'userA')}"}
    _beat("room/status", {"online": False})
    r = c.post("/api/devices/room_light/control", json={"action": "on"}, headers=h)
    assert r.status_code == 409 and r.get_json()["error"] == "device_offline"
    r = c.post("/api/devices/sandy_volume/control", json={"action": "set", "value": "40"},
               headers=h)
    assert r.status_code == 200 and r.get_json()["sent"] is True
    assert broker.sent == [(f"sandy/node/{NODE}/volume", "40")]


# Audit F8: a device's state was written only by commands; the volume and the mics the
# board reports went to the node's telemetry, so «a little lower» on a new robot counted
# from zero and silenced her, and the app showed the mics off while they listened.

def test_the_heartbeat_is_the_state_so_lower_starts_from_the_real_volume(robot, broker):
    from app.brain import tools
    from app.brain.ctx import TurnCtx

    assert device_store.get_device("sandy_volume")["state"] == "70"
    tools.execute("device_control", {"device": "sandy_volume", "by": -20},
                  TurnCtx(user_id="userA"))
    assert broker.sent[-1] == (f"sandy/node/{NODE}/volume", "50")


def test_the_mics_read_as_the_board_has_them(robot):
    brain_beat(mic_l_muted=False, mic_l_gain=150)
    assert device_store.get_device("sandy_mic_left")["state"] == "on"
    assert device_store.get_device("sandy_mic_left_gain")["state"] == "150"
    brain_beat(mic_l_muted=True)
    assert device_store.get_device("sandy_mic_left")["state"] == "off"


def test_a_heartbeat_older_than_a_command_does_not_write_over_it(robot, broker):
    from datetime import datetime, timedelta, timezone

    from app.brain import tools
    from app.brain.ctx import TurnCtx

    tools.execute("device_control", {"device": "sandy_volume", "action": "set", "value": "40"},
                  TurnCtx(user_id="userA"))
    brain_beat(volume=70)                  # left the board before the command reached it
    assert device_store.get_device("sandy_volume")["state"] == "40"
    long_ago = datetime.now(timezone.utc) - timedelta(seconds=device_store.BOARD_STATE_GRACE_S + 1)
    robot["sandy_devices"].update_one({"name": "sandy_volume"}, {"$set": {"state_at": long_ago}})
    brain_beat(volume=45)                  # the board's word, once the command has had its time
    assert device_store.get_device("sandy_volume")["state"] == "45"
