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
                                 {"id": "mic_l_gain", "kind": "audio"},
                                 {"id": "buzzer", "kind": "buzzer"}],
                     **fields})


@pytest.fixture
def robot(brain_db):  # noqa: F811
    brain_db["sandy_nodes"].insert_one({"node_id": NODE, "user_id": "userA", "label": "ساندي",
                                        "outputs": [], "telemetry": {}})
    brain_beat(volume=70)
    with active_user_profile_context(A):
        yield brain_db


def _online() -> dict:
    return {d["name"]: d["online"] for d in device_store.list_devices()}


def test_a_device_whose_board_answers_is_connected(robot):
    on = _online()
    assert on["sandy_volume"] and on["sandy_buzzer"]
    assert device_store.get_device("sandy_buzzer")["online"]


# The camera and the room board were removed (14 Oct 2026). Their rows stay in the
# database; the server passes them over, and an old board still on the broker is not heard.

def test_a_retired_boards_devices_are_passed_over(robot, broker):
    from app.brain import tools
    from app.brain.ctx import TurnCtx

    robot["sandy_devices"].insert_one({
        "user_id": "userA", "name": "room_light", "label": "ضوء الغرفة",
        "control_type": "switch", "transport": {"kind": "node", "node_id": NODE,
                                                "output": "room/light"}})
    assert "room_light" not in _online()
    assert device_store.get_device("room_light") is None
    assert not device_store.tenant_owns_topic(f"sandy/node/{NODE}/room/light")
    out = tools.execute("device_control", {"device": "room_light", "action": "on"},
                        TurnCtx(user_id="userA"))
    assert out["ok"] is False and broker.sent == []
    assert robot["sandy_devices"].count_documents({"name": "room_light"}) == 1   # kept


def test_an_old_board_on_the_broker_is_not_heard(robot):
    robot["sandy_nodes"].update_one({"node_id": NODE}, {"$set": {
        "outputs": [{"id": "volume", "kind": "audio"}, {"id": "cam/flash", "kind": "relay"}],
        "telemetry": {"cam_ip": "192.168.1.6", "ip": "192.168.1.5"}}})
    _beat("room/status", {"online": True, "outputs": [{"id": "light", "kind": "servo"}]})
    _beat("cam/status", {"ip": "192.168.1.7", "outputs": [{"id": "flash", "kind": "relay"}]})
    _beat("cam/event", {"cmd": "snapshot"})
    assert {d["name"] for d in device_store.list_devices()} == {
        "sandy_volume", "sandy_mic_left", "sandy_mic_left_gain", "sandy_buzzer"}
    from app.features.node_store import list_nodes
    node = list_nodes()[0]
    assert "cam/flash" not in [o["id"] for o in node["outputs"]]
    assert "cam_ip" not in node["telemetry"]
    brain_beat()                                     # the next heartbeat drops them for good
    stored = robot["sandy_nodes"].find_one({"node_id": NODE})
    assert all("/" not in o["id"] for o in stored["outputs"])
    assert "cam_ip" not in stored["telemetry"]


def test_the_brain_going_or_in_safe_mode_is_not_connected(robot):
    brain_beat(safe=True)
    assert not _online()["sandy_volume"]
    _beat("status", {"online": False})               # the brain's MQTT will
    assert not _online()["sandy_volume"]


def test_sandy_reads_it_too(robot):
    from app.brain import tools
    from app.brain.ctx import TurnCtx

    rows = tools.execute("device_state", {"device": "sandy_buzzer"}, TurnCtx(user_id="userA"))
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
    monkeypatch.setattr("app.integrations.device_publisher.get_device_publisher", lambda: b)
    return b


def test_a_gone_board_is_not_sent_and_she_says_not_connected(robot, broker):
    from app.brain import tools
    from app.brain.ctx import TurnCtx

    device_store.set_state("sandy_buzzer", "happy")
    _beat("status", {"online": False})
    out = tools.execute("device_control", {"device": "sandy_buzzer", "action": "alert"},
                        TurnCtx(user_id="userA"))
    assert out["ok"] is False and "مش متّصل" in out["reply"]
    assert not out["reply"].startswith("ما اشتغل")      # not «it did not work, try again»
    assert broker.sent == []
    assert device_store.get_device("sandy_buzzer")["state"] == "happy"


def test_a_scene_goes_on_without_the_retired_room_light_and_names_it(robot, broker):
    """A scene saved with the room board's «light» still runs the rest and says what it
    passed over, instead of failing whole."""
    from app.brain import tools
    from app.brain.ctx import TurnCtx
    from app.features import scene_store

    scene_store.add_scene("evening", actions=[{"device": "sandy_volume", "value": "30"},
                                              {"device": "light", "value": "on"}])
    out = tools.execute("scene_apply", {"name": "evening"}, TurnCtx(user_id="userA"))
    assert broker.sent == [(f"sandy/node/{NODE}/volume", "30")]
    assert "ضو الغرفة" in out["reply"] and "تخطّيتها" in out["reply"]


def test_the_app_is_told_not_connected_apart_from_not_reached(robot, broker, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    from app.api.auth_handlers import make_token
    from app.api.server import create_app

    c = create_app(mongo_db=robot).test_client()
    h = {"Authorization": f"Bearer {make_token('user', 'userA')}"}
    r = c.post("/api/devices/sandy_volume/control", json={"action": "set", "value": "40"},
               headers=h)
    assert r.status_code == 200 and r.get_json()["sent"] is True
    assert broker.sent == [(f"sandy/node/{NODE}/volume", "40")]
    _beat("status", {"online": False})
    r = c.post("/api/devices/sandy_volume/control", json={"action": "set", "value": "50"},
               headers=h)
    assert r.status_code == 409 and r.get_json()["error"] == "device_offline"
    assert len(broker.sent) == 1


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


# Audit F9: every dimmer had an on/off switch in the app and the server passed the word on;
# the brain logs it away (the reply said «sent», the state «off»).

def test_no_catalogued_dimmer_takes_on_or_off():
    from app.features.node_provision import PART_CATALOGUE

    dimmers = {o: s for o, s in PART_CATALOGUE.items() if s["control_type"] == "dimmer"}
    assert {"servo", "volume", "mic_l_gain", "mic_r_gain"} <= set(dimmers)
    assert all(s["meta"].get("levels_only") for s in dimmers.values())


def test_on_or_off_on_a_level_only_part_is_refused_with_its_range(robot, broker):
    volume = device_store.get_device("sandy_volume")
    assert device_store.command_payload(volume, "off") == {
        "ok": False, "error": "bad_action", "allowed": ["0..100"]}
    assert device_store.command_payload(volume, "set", "40")["payload"] == "40"
    lamp = {"control_type": "dimmer", "meta": {"min": 0, "max": 100}}
    assert device_store.command_payload(lamp, "off")["payload"] == "off"   # a real dimmer still can


def test_a_part_made_before_the_mark_gets_it_from_the_next_heartbeat(robot):
    robot["sandy_devices"].update_one({"name": "sandy_volume"},
                                      {"$unset": {"meta.levels_only": ""}})
    brain_beat()
    assert device_store.get_device("sandy_volume")["meta"]["levels_only"] is True
