"""A call knows his devices by name, as the chat does.

Audit F19: the voice instruction says «device must be one of those in the prompt», and the
call's prompt had no list (the chat's does). On the robot, «turn on the light» had the model
guess a name, the match is literal, and she asked «which one?» instead of switching it.
"""
from __future__ import annotations

from brain_fakes import A, brain_db  # noqa: F401 — fixture

from app.api.voice_ws.memory import session_context_for
from app.features import device_store
from app.utils.user_profiles import active_user_profile_context


def _kitchen(db):
    db["sandy_nodes"].insert_one({"node_id": "x", "user_id": "userA", "telemetry": {}})
    with active_user_profile_context(A):
        assert device_store.add_device("kitchen", "ضو المطبخ", "switch",
                                       {"kind": "node", "node_id": "x", "output": "room/light"},
                                       room="المطبخ")["ok"]


def test_the_call_is_told_his_devices(brain_db):  # noqa: F811
    _kitchen(brain_db)
    text = session_context_for("userA", "الروبوت", "نبيل", history=[])
    assert "ضو المطبخ (kitchen، المطبخ)" in text


def test_another_tenants_devices_are_not_in_it(brain_db):  # noqa: F811
    _kitchen(brain_db)
    assert "ضو المطبخ" not in session_context_for("userB", "الروبوت", "", history=[])
