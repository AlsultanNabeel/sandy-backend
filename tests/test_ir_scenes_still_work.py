"""The robot's infrared and the scenes that use it, after the camera and the room board left.

IR lives on the brain (`sandy_ir.c`, output `ir`, one level under the robot), so removing
the other boards must not touch it: a learned button is sent as its code, a scene that
holds an IR button sends it, and the brain still builds with IR on.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from brain_fakes import A, brain_db  # noqa: F401 — fixture

from app.brain import tools
from app.brain.ctx import TurnCtx
from app.features import device_store, scene_store
from app.integrations import mqtt_ingest
from app.utils.user_profiles import active_user_profile_context

NODE = "8421"
CODE = "9000,4500,560,560,560,1690"


class _Broker:
    def __init__(self):
        self.sent = []

    def send_to_topic(self, topic, payload):
        self.sent.append((topic, payload))
        return True


@pytest.fixture
def robot(brain_db, monkeypatch):  # noqa: F811
    brain_db["sandy_nodes"].insert_one({"node_id": NODE, "user_id": "userA", "label": "ساندي",
                                        "outputs": [], "telemetry": {}})
    mqtt_ingest._handle_message(f"sandy/node/{NODE}/status", json.dumps({
        "online": True, "outputs": [{"id": "ir", "kind": "ir"},
                                    {"id": "volume", "kind": "audio"}]}).encode())
    broker = _Broker()
    monkeypatch.setattr("app.integrations.device_publisher.get_device_publisher", lambda: broker)
    with active_user_profile_context(A):
        assert device_store.learn_ir_button("sandy_ir", "tv_power", CODE)["ok"]
        yield broker


def test_the_robot_still_has_its_remote(robot):
    ir = device_store.get_device("sandy_ir")
    assert ir and ir["control_type"] == "ir" and ir["online"]
    assert device_store.device_topic(ir) == f"sandy/node/{NODE}/ir"


def test_a_learned_button_is_sent_as_its_code(robot):
    out = tools.execute("device_control", {"device": "sandy_ir", "action": "tv_power"},
                        TurnCtx(user_id="userA"))
    assert out["ok"], out
    assert robot.sent == [(f"sandy/node/{NODE}/ir", CODE)]


def test_a_scene_with_an_ir_button_sends_it(robot):
    scene_store.add_scene("movie", actions=[{"device": "sandy_ir", "value": "tv_power"},
                                            {"device": "sandy_volume", "value": "30"}])
    out = tools.execute("scene_apply", {"name": "movie"}, TurnCtx(user_id="userA"))
    assert out["ok"], out
    assert (f"sandy/node/{NODE}/ir", CODE) in robot.sent
    assert (f"sandy/node/{NODE}/volume", "30") in robot.sent


def test_learning_is_still_armed_on_the_robot(robot):
    assert device_store.tenant_owns_topic(f"sandy/node/{NODE}/ir")
    assert mqtt_ingest._IR_SUB == "sandy/node/+/ir/learned"


def test_the_brain_still_builds_with_ir_on():
    root = Path(__file__).resolve().parent.parent / "firmware/brain-core/main"
    assert "#define ENABLE_IR       1" in (root / "include/config.h").read_text(encoding="utf-8")
    assert (root / "sandy_ir.c").exists()
