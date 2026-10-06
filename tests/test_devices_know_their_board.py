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
