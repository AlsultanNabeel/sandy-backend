"""Regression tests for the security/correctness hardening waves.

Locks in the fixes so they can't silently regress:
- unified Arabic yes/no confirmation matching (the "اه" → hallucinated حذفت bug),
- per-user pending-state key isolation,
- device transport validation (reserved node namespace).
"""

from app.brain.confirm import answer
from app.brain.pending import _key as pending_key
from app.features.device_store import _valid_transport


# ── confirmation matching ────────────────────────────────────────────────────

def test_confirmations_recognized():
    for t in ["اه", "آه", "أه", "اه صح", "اه احذفها", "اه 👍", "تمام", "نعم",
              "ايوه", "احذفها", "ok", "okay", "تمام يلا", "تمام لا مشكلة"]:
        assert answer(t) == "yes", t


def test_cancellations_recognized_and_win_mixed():
    for t in ["لا", "لأ", "مش هلأ", "الغي", "خلص", "no", "cancel", "لا تحذف",
              "اه بس لا"]:
        assert answer(t) == "no", t


def test_non_answers_are_ignored_not_confirmed():
    for t in ["شو الطقس اليوم", "اي واحدة", "احكيلي قصة", ""]:
        assert answer(t) == "other", t


# ── pending-state key isolation ──────────────────────────────────────────────

def test_pending_key_is_tenant_scoped():
    # Two users sharing a client-supplied conversation_id must not collide.
    assert pending_key("userA", "default") != pending_key("userB", "default")
    assert pending_key("userA", "default") == "userA:default"


# ── device transport validation ──────────────────────────────────────────────

def test_a_device_is_a_node_output_only():
    """Audit T7: a raw MQTT topic let any tenant publish anywhere outside the node tree on
    the server's own broker login (and, were that login confined, every refused publish
    would drop the server off the broker for everyone); a web address was never sent."""
    assert _valid_transport({"kind": "mqtt", "topic": "sandy/node/x/relay"}) is False
    assert _valid_transport({"kind": "mqtt", "topic": "room/cmd/light"}) is False
    assert _valid_transport({"kind": "wifi_api", "url": "http://192.168.1.5/on"}) is False
    assert _valid_transport({"kind": "node", "node_id": "x", "output": "relay1"}) is True


def test_a_device_saved_with_a_raw_topic_is_listed_and_reaches_nothing(monkeypatch):
    """Rows saved before raw topics were removed stay visible (the app marks them «not
    supported» with a delete), and no command is published for them."""
    import mongomock

    from app import db as appdb
    from app.brain import tools
    from app.brain.ctx import TurnCtx
    from app.features import device_store
    from app.utils.user_profiles import active_user_profile_context

    d = mongomock.MongoClient().db
    appdb.configure(d)
    sent = []

    class _Client:
        def send_to_topic(self, topic, payload):
            sent.append(topic)
            return True

    monkeypatch.setattr("app.integrations.room_device.get_room_device_client", lambda: _Client())
    try:
        d["sandy_devices"].insert_one({"user_id": "u1", "name": "lamp", "label": "لمبتي",
                                       "control_type": "switch",
                                       "transport": {"kind": "mqtt", "topic": "home/lamp"}})
        with active_user_profile_context({"chat_id": "u1", "relation": "user"}):
            assert [x["transport"]["kind"] for x in device_store.list_devices()] == ["mqtt"]
            out = tools.execute("device_control", {"device": "lamp", "action": "on"},
                                TurnCtx(user_id="u1"))
            assert out["ok"] is False and "ما عادت مدعومة" in out["reply"] and sent == []
            assert device_store.update_device(
                "lamp", transport={"kind": "mqtt", "topic": "x/y"})["error"] == "bad_transport"
            assert device_store.delete_device("lamp")["ok"]
    finally:
        appdb.reset()
