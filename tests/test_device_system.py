"""Device system tests — the registry, validation, pairing, and the anti-
hallucination control path. No hardware needed: actuation is mocked, everything
else runs over a mongomock database scoped per tenant.

The headline guarantee under test: device_control may only act on a REGISTERED
device with a VALIDATED action; an unknown device or a wrong action is REFUSED
(Sandy asks) — it never guesses and never applies the opposite ("on" -> "off").
"""

import os

import mongomock
import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-for-devices")

from app.utils.user_profiles import active_user_profile_context  # noqa: E402
from app.features import device_store, node_store  # noqa: E402


def as_tenant(tenant_id):
    return active_user_profile_context(
        {"chat_id": tenant_id, "permissions": "all", "relation": "user"}
    )


@pytest.fixture()
def db():
    database = mongomock.MongoClient().db
    device_store.init_device_store(database)
    node_store.init_node_store(database)
    return database


def _add_light(name="living_light", label="ضوء الصالة"):
    return device_store.add_device(
        name=name, label=label, control_type="dimmer",
        transport={"kind": "mqtt", "topic": "room/cmd/light"},
        room="salon", meta={"min": 0, "max": 100},
    )


# ── command_payload: the one validator ──────────────────────────────────────

def test_switch_validation():
    dev = {"control_type": "switch", "meta": {}}
    assert device_store.command_payload(dev, "on") == {"ok": True, "payload": "on"}
    assert device_store.command_payload(dev, "off")["payload"] == "off"
    bad = device_store.command_payload(dev, "dim")
    assert bad["ok"] is False and "on" in bad["allowed"]


def test_dimmer_validation_clamps_and_accepts_level():
    dev = {"control_type": "dimmer", "meta": {"min": 0, "max": 100}}
    assert device_store.command_payload(dev, "on")["payload"] == "on"
    assert device_store.command_payload(dev, "set", "60")["payload"] == "60"
    # clamps out-of-range
    assert device_store.command_payload(dev, "set", "250")["payload"] == "100"
    # the action itself being a number is accepted
    assert device_store.command_payload(dev, "40")["payload"] == "40"
    assert device_store.command_payload(dev, "banana")["ok"] is False


def test_enum_validation_rejects_unknown_value():
    dev = {"control_type": "enum", "meta": {"values": ["warm", "cool", "red"]}}
    assert device_store.command_payload(dev, "set", "red")["payload"] == "red"
    assert device_store.command_payload(dev, "warm")["payload"] == "warm"
    bad = device_store.command_payload(dev, "set", "magenta")
    assert bad["ok"] is False and bad["allowed"] == ["warm", "cool", "red"]


def test_cover_and_media_validation():
    cover = {"control_type": "cover", "meta": {}}
    assert device_store.command_payload(cover, "open")["payload"] == "open"
    assert device_store.command_payload(cover, "close")["payload"] == "close"
    assert device_store.command_payload(cover, "on")["ok"] is False
    media = {"control_type": "media", "meta": {}}
    assert device_store.command_payload(media, "pause")["payload"] == "pause"
    assert device_store.command_payload(media, "open")["ok"] is False


def test_ir_requires_learned_button():
    dev = {"control_type": "ir", "meta": {"buttons": {"power": "CODE_A"}}}
    ok = device_store.command_payload(dev, "send", "power")
    assert ok["ok"] is True and ok["payload"] == "CODE_A"
    bad = device_store.command_payload(dev, "send", "turbo")
    assert bad["ok"] is False and bad["error"] == "not_learned"


# ── CRUD + tenant isolation ─────────────────────────────────────────────────

def test_add_validates_and_rejects_duplicates(db):
    with as_tenant("t1"):
        assert _add_light()["ok"] is True
        assert _add_light()["error"] == "exists"
        assert device_store.add_device("BadName!", "x", "switch",
                                       {"kind": "mqtt", "topic": "t"})["error"] == "bad_name"
        assert device_store.add_device("x", "x", "telepathy",
                                       {"kind": "mqtt", "topic": "t"})["error"] == "bad_control_type"
        assert device_store.add_device("x", "x", "switch", {"kind": "mqtt"})["error"] == "bad_transport"


def test_registry_starts_empty_no_seeding(db):
    with as_tenant("fresh"):
        assert device_store.list_devices() == []


def test_devices_are_tenant_scoped(db):
    with as_tenant("t1"):
        _add_light()
        assert len(device_store.list_devices()) == 1
    with as_tenant("t2"):
        assert device_store.list_devices() == []  # t1's device is invisible to t2


def test_update_and_delete(db):
    with as_tenant("t1"):
        _add_light()
        assert device_store.update_device("living_light", label="ضوء جديد")["ok"] is True
        assert device_store.get_device("living_light")["label"] == "ضوء جديد"
        assert device_store.delete_device("living_light")["ok"] is True
        assert device_store.delete_device("living_light")["error"] == "not_found"


def test_device_topic_for_mqtt_and_node():
    assert device_store.device_topic(
        {"transport": {"kind": "mqtt", "topic": "room/cmd/fan"}}) == "room/cmd/fan"
    assert device_store.device_topic(
        {"transport": {"kind": "node", "node_id": "n_abc", "output": "relay1"}}
    ) == "sandy/node/n_abc/relay1"
    assert device_store.device_topic({"transport": {"kind": "mqtt"}}) is None


# ── Node pairing ────────────────────────────────────────────────────────────

def test_pairing_is_idempotent_and_scoped(db):
    with as_tenant("t1"):
        r1 = node_store.pair_node("ABCD-1234", "صندوق الصالة")
        assert r1["ok"] is True and r1["already"] is False
        r2 = node_store.pair_node("ABCD-1234")
        assert r2["already"] is True and r2["node_id"] == r1["node_id"]
        assert len(node_store.list_nodes()) == 1
        assert node_store.pair_node("xy")["error"] == "bad_code"
    with as_tenant("t2"):
        assert node_store.list_nodes() == []


def test_node_heartbeat_filters_unknown_capabilities(db):
    with as_tenant("t1"):
        node_store.pair_node("CODE-9999")
    res = node_store.set_node_status("CODE-9999", online=True,
                                     capabilities=["relay", "telepathy", "ir"])
    assert res["ok"] is True
    with as_tenant("t1"):
        node = node_store.list_nodes()[0]
        assert node["online"] is True
        assert set(node["capabilities"]) == {"relay", "ir"}
    assert node_store.set_node_status("NO-SUCH-CODE")["error"] == "unknown_node"


# ── device_control tool: the anti-hallucination guarantee ───────────────────

@pytest.fixture()
def mock_actuation(monkeypatch):
    """Pretend the broker accepts every publish, and capture what was sent."""
    sent = {}

    class _Client:
        def send_to_topic(self, topic, payload):
            sent["topic"], sent["payload"] = topic, payload
            return True

    monkeypatch.setattr(
        "app.integrations.room_device.get_room_device_client", lambda: _Client()
    )
    return sent


def test_control_unknown_device_refuses_and_asks(db, mock_actuation):
    from app.agent.tools.schemas.device_tools import device_control

    with as_tenant("t1"):
        _add_light()
        out = device_control({"device": "غسالة", "action": "on"}, None)
    assert out["handled"] is True
    assert "ضوء الصالة" in out["reply"]          # lists what's available
    assert "topic" not in mock_actuation          # nothing was actuated


def test_control_on_actuates_real_topic(db, mock_actuation):
    from app.agent.tools.schemas.device_tools import device_control

    with as_tenant("t1"):
        _add_light()
        out = device_control({"device": "living_light", "action": "on"}, None)
    assert mock_actuation["topic"] == "room/cmd/light"
    assert mock_actuation["payload"] == "on"
    assert "شغّلت" in out["reply"]


def test_control_never_applies_the_opposite(db, mock_actuation):
    """'on' must send 'on' — never silently flip to 'off' (the original bug)."""
    from app.agent.tools.schemas.device_tools import device_control

    with as_tenant("t1"):
        _add_light()
        device_control({"device": "living_light", "action": "on"}, None)
    assert mock_actuation["payload"] == "on"
    assert mock_actuation["payload"] != "off"


def test_control_bad_action_refuses_without_actuating(db, mock_actuation):
    from app.agent.tools.schemas.device_tools import device_control

    with as_tenant("t1"):
        device_store.add_device("salon_curtain", "ستارة", "cover",
                                {"kind": "mqtt", "topic": "room/cmd/curtain"})
        out = device_control({"device": "salon_curtain", "action": "on"}, None)
    assert "المتاح" in out["reply"]               # tells the allowed actions
    assert "topic" not in mock_actuation          # refused, nothing sent


def test_scene_actuates_registry_device_via_validated_path(db, mock_actuation, monkeypatch):
    """A scene action on a registered device goes through command_payload +
    device_topic (the same validated path device_control uses), not the old vocab."""
    monkeypatch.setattr("app.utils.user_profiles.is_owner_chat_id", lambda x: True)
    from app.agent.tools.schemas.life_tools import actuate_scene_actions

    with as_tenant("t1"):
        _add_light()  # dimmer "living_light" -> room/cmd/light
        sent = actuate_scene_actions([{"device": "living_light", "value": "on"}])
    assert sent is True
    assert mock_actuation["topic"] == "room/cmd/light"
    assert mock_actuation["payload"] == "on"


def test_device_catalog_lists_registered_devices_only(db):
    from app.agent.tools.schemas.device_tools import build_device_catalog

    with as_tenant("t1"):
        _add_light()
        catalog = build_device_catalog()
    assert "living_light" in catalog
    assert "on|off" in catalog
    with as_tenant("t2"):
        assert build_device_catalog() == ""       # other tenant sees nothing
