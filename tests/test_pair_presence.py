"""Pairing needs the code on her face, not only the code on her box.

A photo of the sticker was enough to claim somebody's robot. Now the printed
code starts pairing; the six digits the robot shows finish it.
"""
from __future__ import annotations

import mongomock
import pytest


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    from app.api.server import create_app
    from app.features import pair_presence

    sent = []
    monkeypatch.setattr(pair_presence, "_publish",
                        lambda node_id, code: sent.append((node_id, code)) or True)
    db = mongomock.MongoClient().db
    app = create_app(mongo_db=db, semantic_memory_stats_fn=lambda: {})
    return app.test_client(), db, sent


def _h(uid):
    from app.api.auth_handlers import make_token
    return {"Authorization": f"Bearer {make_token('user', user_id=uid)}"}


def test_the_box_code_alone_does_not_pair_a_free_robot(env):
    c, db, sent = env
    r = c.post("/api/nodes/pair", json={"code": "SANDY-8421"}, headers=_h("alice"))
    assert r.status_code == 202, r.get_json()
    body = r.get_json()
    assert body["needs_presence"] is True and body["node_id"] == "sandy8421"
    assert sent and sent[0][0] == "sandy8421" and len(sent[0][1]) == 6
    # Nothing is claimed yet.
    assert db["sandy_nodes"].count_documents({}) == 0


def test_the_code_on_her_face_finishes_it(env):
    c, db, sent = env
    c.post("/api/nodes/pair", json={"code": "SANDY-8421"}, headers=_h("alice"))
    shown = sent[-1][1]
    r = c.post("/api/nodes/pair/confirm",
               json={"code": "SANDY-8421", "presence": shown, "label": "Sandy"},
               headers=_h("alice"))
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["node_id"] == "sandy8421"
    # Used once: the same digits do not pair again for someone else.
    r2 = c.post("/api/nodes/pair/confirm",
                json={"code": "SANDY-8421", "presence": shown}, headers=_h("mallory"))
    assert r2.status_code == 400
    assert r2.get_json()["error"] == "already_claimed"


def test_wrong_digits_are_counted_and_then_the_challenge_ends(env):
    c, _, sent = env
    c.post("/api/nodes/pair", json={"code": "SANDY-8421"}, headers=_h("alice"))
    shown = sent[-1][1]
    wrong = "000000" if shown != "000000" else "111111"
    for i in range(5):
        r = c.post("/api/nodes/pair/confirm",
                   json={"code": "SANDY-8421", "presence": wrong}, headers=_h("alice"))
        assert r.get_json()["error"] == "presence_wrong", i
    # The sixth try is refused even with the right digits — by the challenge
    # (locked) or, first, by the per-account rate limit on this endpoint.
    r = c.post("/api/nodes/pair/confirm",
               json={"code": "SANDY-8421", "presence": shown}, headers=_h("alice"))
    assert r.get_json()["error"] in ("presence_locked", "too_many_attempts")
    from app.features import pair_presence
    assert pair_presence.confirm("sandy8421", "alice", shown)["error"] == "presence_locked"


def test_the_code_belongs_to_the_account_that_asked(env):
    c, _, sent = env
    c.post("/api/nodes/pair", json={"code": "SANDY-8421"}, headers=_h("alice"))
    shown = sent[-1][1]
    r = c.post("/api/nodes/pair/confirm",
               json={"code": "SANDY-8421", "presence": shown}, headers=_h("mallory"))
    assert r.status_code == 400 and r.get_json()["error"] == "presence_missing"


def test_an_expired_code_is_refused(env, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from app.features import pair_presence

    c, db, sent = env
    c.post("/api/nodes/pair", json={"code": "SANDY-8421"}, headers=_h("alice"))
    db["node_pair_challenges"].update_many(
        {}, {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}})
    r = c.post("/api/nodes/pair/confirm",
               json={"code": "SANDY-8421", "presence": sent[-1][1]}, headers=_h("alice"))
    assert r.get_json()["error"] == "presence_expired"
    assert pair_presence.TTL_SECONDS == 300


def test_re_pairing_your_own_robot_needs_no_proof(env):
    c, _, sent = env
    c.post("/api/nodes/pair", json={"code": "SANDY-8421"}, headers=_h("alice"))
    c.post("/api/nodes/pair/confirm",
           json={"code": "SANDY-8421", "presence": sent[-1][1]}, headers=_h("alice"))
    n = len(sent)
    r = c.post("/api/nodes/pair", json={"code": "SANDY-8421"}, headers=_h("alice"))
    assert r.status_code == 200 and r.get_json()["already"] is True
    assert len(sent) == n, "no new code for a robot that is already yours"


def test_the_brain_shows_the_code_and_ignores_a_retained_one():
    from pathlib import Path
    mq = (Path(__file__).resolve().parent.parent / "firmware" / "brain-core" / "main"
          / "sandy_mqtt.c").read_text()
    assert '!strcmp(out, "pair_code")' in mq
    assert '!strcmp(out, "pair_code")' in mq[mq.index("static bool _is_one_shot"):]


def test_the_app_asks_for_the_code_on_her_screen():
    from pathlib import Path
    ios = Path(__file__).resolve().parent.parent / "ios" / "SandyApp"
    api = (ios / "Core" / "Networking" / "APIClient+Devices.swift").read_text()
    assert '"/api/nodes/pair/confirm"' in api and 'case needsPresence = "needs_presence"' in api
    sheet = (ios / "Features" / "Control" / "NodeSheets.swift").read_text()
    for code in ("presence_wrong", "presence_expired", "presence_locked", "already_claimed"):
        assert f'"{code}"' in sheet, code
    l10n = (ios / "Localization" / "L10n+Control.swift").read_text()
    for key in ("presenceHeader", "presenceWrong", "presenceNotSent", "presenceResend"):
        assert l10n.count(f'"node.{key}"') == 2, f"{key} needs Arabic and English"
    account = (ios / "Features" / "Profile" / "AccountView.swift").read_text()
    assert "res.needsPresence" in account, "the account screen pairs too"
