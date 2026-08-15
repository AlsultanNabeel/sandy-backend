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


# ── Per-tenant actuation ownership (replaces the old owner-only gate) ────────
#
# The actuation boundary used to ask "is the caller the owner?", which is the
# right question for one person's house and the wrong one for a product other
# people buy: a second tenant could register a device and then not be allowed to
# switch it on. It now asks "does this topic belong to a device in the CALLING
# tenant's registry?" — so everyone drives their own hardware, and nobody
# reaches anyone else's.

def test_tenant_owns_only_its_own_device_topic(db):
    with as_tenant("tenant-a"):
        _add_light(name="a_light")
        assert device_store.tenant_owns_topic("room/cmd/light") is True

    # Same topic string, different tenant, no device registered -> refused.
    with as_tenant("tenant-b"):
        assert device_store.tenant_owns_topic("room/cmd/light") is False


def test_unknown_topic_is_refused_even_for_a_tenant_with_devices(db):
    with as_tenant("tenant-a"):
        _add_light(name="a_light")
        assert device_store.tenant_owns_topic("room/cmd/curtain") is False
        assert device_store.tenant_owns_topic("") is False


def test_ownership_fails_closed_without_a_tenant(db):
    # No active profile => no tenant => the scoped read returns nothing.
    assert device_store.tenant_owns_topic("room/cmd/light") is False


def test_node_transport_topic_is_owned_by_the_pairing_tenant(db):
    with as_tenant("tenant-a"):
        node_store.pair_node("sandybrain01", "عقل ساندي")
        device_store.add_device(
            name="face", label="وش ساندي", control_type="enum",
            transport={"kind": "node", "node_id": "sandybrain01", "output": "mood"},
            meta={"values": ["happy", "sad", "curious", "alert"]},
        )
        assert device_store.tenant_owns_topic("sandy/node/sandybrain01/mood") is True

    with as_tenant("tenant-b"):
        assert device_store.tenant_owns_topic("sandy/node/sandybrain01/mood") is False


# ── The robot arrives with its own parts ─────────────────────────────────────
#
# Someone buys the robot, pairs it, opens the Control tab. Her face, her neck and
# her mics have to be there already — they came in the box. But nothing may be
# seeded from code: a board that does not report a servo must not show a neck.
# So the hardware declares its outputs and the backend provisions what it hears.

ROBOT_OUTPUTS = [
    {"id": "mood", "kind": "pwm"},
    {"id": "servo", "kind": "servo"},
    {"id": "mic_l", "kind": "audio"},
    {"id": "mic_r", "kind": "audio"},
    {"id": "volume", "kind": "audio"},
]


def test_pairing_a_robot_gives_the_owner_its_parts(db):
    from app.features import node_provision

    with as_tenant("owner"):
        node_store.pair_node("sandybrain01", "ساندي")
        # The board comes online and declares what it has.
        node_store.ingest_status("sandybrain01", True, ["servo", "audio"],
                                 ROBOT_OUTPUTS, "0.4.0")

        names = {d["name"] for d in device_store.list_devices()}
        assert "sandy_face" in names
        assert "sandy_head" in names
        assert "sandy_mic_left" in names and "sandy_mic_right" in names
        assert "sandy_volume" in names
        assert node_provision.PART_CATALOGUE["mood"]["control_type"] == "enum"


def test_a_part_the_board_never_reported_does_not_appear(db):
    with as_tenant("owner"):
        node_store.pair_node("sandybrain01", "ساندي")
        # This unit has no neck and no buzzer.
        node_store.ingest_status("sandybrain01", True, ["audio"],
                                 [{"id": "mic_l", "kind": "audio"}], "0.4.0")

        names = {d["name"] for d in device_store.list_devices()}
        assert "sandy_mic_left" in names
        assert "sandy_head" not in names
        assert "sandy_buzzer" not in names


def test_provisioned_parts_are_driveable_by_their_owner_only(db):
    with as_tenant("owner"):
        node_store.pair_node("sandybrain01", "ساندي")
        node_store.ingest_status("sandybrain01", True, ["servo"],
                                 ROBOT_OUTPUTS, "0.4.0")
        face = device_store.get_device("sandy_face")
        topic = device_store.device_topic(face)
        assert topic == "sandy/node/sandybrain01/mood"
        assert device_store.tenant_owns_topic(topic) is True

    # Somebody else's robot is not theirs to drive.
    with as_tenant("stranger"):
        assert device_store.tenant_owns_topic("sandy/node/sandybrain01/mood") is False


def test_provisioning_is_idempotent_and_keeps_owner_edits(db):
    with as_tenant("owner"):
        node_store.pair_node("sandybrain01", "ساندي")
        node_store.ingest_status("sandybrain01", True, [], ROBOT_OUTPUTS, "0.4.0")
        device_store.update_device("sandy_head", label="رقبتها")

        # A second heartbeat, and a firmware upgrade that adds a part.
        node_store.ingest_status("sandybrain01", True, [],
                                 ROBOT_OUTPUTS + [{"id": "noise", "kind": "audio"}],
                                 "0.5.0")

        devices = device_store.list_devices()
        assert len([d for d in devices if d["name"] == "sandy_head"]) == 1
        assert device_store.get_device("sandy_head")["label"] == "رقبتها"
        assert "sandy_noise" in {d["name"] for d in devices}


def test_an_unpaired_board_provisions_nothing(db):
    # It is powered on and shouting into the broker before anyone typed its code.
    res = node_store.ingest_status("nobodysnode", True, [], ROBOT_OUTPUTS, "0.4.0")
    assert res["ok"] is False
    with as_tenant("owner"):
        assert device_store.list_devices() == []


def test_the_board_reports_its_own_address(db):
    """The robot's IP changes whenever the router reassigns it, and without the
    board saying so, finding it means scanning the network and guessing — which
    is exactly what stalled a flash once."""
    with as_tenant("owner"):
        node_store.pair_node("sandybrain01", "ساندي")
        node_store.ingest_status(
            "sandybrain01", True, [], ROBOT_OUTPUTS, "0.5.0",
            telemetry={"ip": "192.168.1.102", "board": "sandy-brain-s3", "volume": 80},
        )
        node = node_store.get_node("sandybrain01")
        assert node["telemetry"]["ip"] == "192.168.1.102"
        assert node["telemetry"]["board"] == "sandy-brain-s3"
        assert node["telemetry"]["volume"] == 80


def test_a_hostile_heartbeat_cannot_stuff_the_node_document(db):
    """The payload arrives over a shared broker from a device nobody
    authenticated. Long strings get truncated and unknown keys are dropped."""
    with as_tenant("owner"):
        node_store.pair_node("sandybrain01", "ساندي")
        node_store.ingest_status(
            "sandybrain01", True, [], ROBOT_OUTPUTS, "0.5.0",
            telemetry={"ip": "x" * 500, "evil": "drop me", "volume": "not a number"},
        )
        tele = node_store.get_node("sandybrain01")["telemetry"]
        assert len(tele["ip"]) == 32          # truncated, not stored whole
        assert "evil" not in tele             # not on the allowlist
        assert "volume" not in tele           # unparseable, dropped, rest survives
