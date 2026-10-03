"""A camera that is off says so at once: no photo ticket, no stream, no «not yet» for ever.

Live (2026-10-03): the camera was not on the Wi-Fi, and the app polled «pending» for two
minutes, then showed a placeholder that never ended.
"""
from __future__ import annotations

import pytest
from brain_fakes import brain_db  # noqa: F401 — fixture

from app.utils.user_profiles import active_user_profile_context


@pytest.fixture()
def c(monkeypatch, brain_db):  # noqa: F811
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    from app.api.server import create_app
    app = create_app(mongo_db=brain_db)
    return app.test_client()


def _h():
    from app.api.auth_handlers import make_token
    return {"Authorization": f"Bearer {make_token('user', 'userA')}"}


@pytest.fixture()
def node(brain_db, monkeypatch):  # noqa: F811
    from app.features import device_store
    brain_db["sandy_nodes"].insert_one({"node_id": "8421", "user_id": "userA",
                                        "telemetry": {"cam_online": False}})
    with active_user_profile_context({"chat_id": "userA", "relation": "user"}):
        assert device_store.add_device("cam_stream", "بث", "switch",
                                       {"kind": "node", "node_id": "8421",
                                        "output": "cam/stream"})["ok"]
    sent = []
    monkeypatch.setattr("app.integrations.camera_client._send",
                        lambda node_id, cmd: sent.append(cmd) or True)
    return sent


def test_an_offline_camera_is_refused_at_once(c, node):
    for method, path in (("POST", "/api/nodes/8421/snapshot"),
                         ("GET", "/api/nodes/8421/snapshot/live"),
                         ("GET", "/api/nodes/8421/snapshot/abc123")):
        r = c.open(path, method=method, headers=_h())
        assert r.status_code == 409 and r.get_json()["error"] == "camera_offline", path
    r = c.post("/api/devices/cam_stream/control", json={"action": "on"}, headers=_h())
    assert r.status_code == 409
    assert node == []                     # nothing was asked of a camera that is not there


def test_an_online_camera_is_still_asked(c, node, brain_db):  # noqa: F811
    brain_db["sandy_nodes"].update_one({"node_id": "8421"},
                                       {"$set": {"telemetry.cam_online": True}})
    r = c.get("/api/nodes/8421/snapshot/abc123", headers=_h())
    assert r.status_code == 202
