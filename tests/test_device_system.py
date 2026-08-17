"""Device system tests — the registry, validation, pairing, and the anti-
hallucination control path. No hardware needed: actuation is mocked, everything
else runs over a mongomock database scoped per tenant.

The headline guarantee under test: device_control may only act on a REGISTERED
device with a VALIDATED action; an unknown device or a wrong action is REFUSED
(Sandy asks) — it never guesses and never applies the opposite ("on" -> "off").
"""

import io
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


def test_a_firmware_upgrade_widens_an_existing_device_vocabulary(db):
    """A part that learns new tricks must not stay stuck on the old menu.

    This is a real regression. The speaker was provisioned when it had one sound;
    firmware later gave it six, but provisioning skipped every device that already
    existed, so the app kept offering the single sound it was born with and the
    five new ones were unreachable. The upgrade looked like it had failed.

    The owner's label stays theirs — only the accepted values follow the firmware,
    because that list is the firmware's vocabulary, not a preference.
    """
    from app.features import node_provision

    with as_tenant("owner"):
        node_store.pair_node("sandybrain01", "ساندي")
        node_store.ingest_status("sandybrain01", True, [],
                                 [{"id": "speaker_test", "kind": "audio"}], "0.5.0")
        # Roll it back to the one-sound state a board provisioned before the
        # upgrade would be sitting in.
        device_store.update_device("sandy_speaker_test",
                                   label="سماعتها", meta={"values": ["beep"]})

        node_store.ingest_status("sandybrain01", True, [],
                                 [{"id": "speaker_test", "kind": "audio"}], "0.6.0")

        dev = device_store.get_device("sandy_speaker_test")
        assert dev["meta"]["values"] == \
            node_provision.PART_CATALOGUE["speaker_test"]["meta"]["values"]
        assert len(dev["meta"]["values"]) > 1
        assert dev["label"] == "سماعتها"   # still the owner's


def test_a_settled_vocabulary_is_not_rewritten_every_heartbeat(db):
    """A heartbeat lands every five seconds. If provisioning wrote on each one,
    the refresh above would be a busy loop wearing on the database forever."""
    from app.features.node_provision import provision_from_outputs

    with as_tenant("owner"):
        node_store.pair_node("sandybrain01", "ساندي")
        outs = [{"id": "speaker_test", "kind": "audio"}]
        node_store.ingest_status("sandybrain01", True, [], outs, "0.6.0")

        res = provision_from_outputs("sandybrain01", outs)
        assert res["added"] == []
        assert res["refreshed"] == []


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


def test_the_hardware_document_matches_the_hardware():
    """The inventory is generated, and this fails the build when it drifts.

    Its hand-written predecessor was wrong in five places within a month — the
    mood count, the microphone gain, the buzzer's flag — and it was quoted as a
    source in a readiness report while wrong. A second copy of the truth always
    drifts; the only fix that holds is to derive it and to notice immediately.
    """
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parent.parent / "scripts" / "gen_hardware_doc.py"
    result = subprocess.run([sys.executable, str(script), "--check"],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, (
        f"{result.stdout.strip()}\n"
        "The firmware or the catalogue changed and the document did not. "
        "Run: python3 scripts/gen_hardware_doc.py"
    )


def test_the_ownership_check_finds_exactly_what_it_used_to_scan_for(db):
    """`_topic_query` is `device_topic` run backwards. Pin the two together.

    The check runs on every actuation and used to read every device the tenant
    owned, deriving each one's topic in Python. Now it is a single lookup, which
    is only safe while the two directions agree — so this builds devices of every
    transport shape, derives each topic the forward way, and asserts the backward
    query finds it.
    """
    from app.features.device_store import _topic_query, device_topic

    with as_tenant("owner"):
        node_store.pair_node("sandybrain01", "ساندي")
        node_store.ingest_status("sandybrain01", True, [], ROBOT_OUTPUTS, "0.6.0")
        device_store.add_device(
            name="lamp", label="لمبة", control_type="switch",
            transport={"kind": "mqtt", "topic": "room/cmd/light"}, room="صالة",
        )

        for dev in device_store.list_devices():
            raw = device_store.get_device(dev["name"])
            topic = device_topic(raw)
            if topic is None:
                continue
            assert device_store.tenant_owns_topic(topic), (
                f"{dev['name']}: derived {topic}, and the reverse query missed it"
            )
            # ...and the query is specific, not a match-anything.
            assert "$exists" not in str(_topic_query(topic))


def test_a_topic_from_another_account_is_still_refused(db):
    """The scan-to-lookup change must not widen what counts as owned."""
    with as_tenant("owner"):
        node_store.pair_node("sandybrain01", "ساندي")
        node_store.ingest_status("sandybrain01", True, [], ROBOT_OUTPUTS, "0.6.0")

    with as_tenant("stranger"):
        assert device_store.tenant_owns_topic("sandy/node/sandybrain01/servo") is False
        assert device_store.tenant_owns_topic("sandy/node/sandybrain01") is False
        assert device_store.tenant_owns_topic("sandy/node//servo") is False
        assert device_store.tenant_owns_topic("") is False


def test_the_camera_reports_its_address_the_same_way_the_brain_does(db):
    """One heartbeat shape for every board, so one code path reads them all.

    "What is the camera's IP?" had no answer anywhere in the system: the router
    hands out an address that changes, and the camera told nobody. A simple
    question ended in scanning 254 addresses and guessing which board replied.

    The camera now sends `ip` and `board` — the same two fields the brain sends,
    landing in the same telemetry allowlist, needing no new server code. This
    test is what keeps that true: if either board renames a field, it fails here
    rather than showing an empty row in the app.
    """
    with as_tenant("owner"):
        node_store.pair_node("sandycam01", "الكاميرا")
        node_store.ingest_status(
            "sandycam01", True, [], [], "0.2.0",
            telemetry={"ip": "192.168.1.117", "board": "sandy-cam",
                       "uptime": 900, "heap": 120000},
        )
        node = node_store.get_node("sandycam01")
        assert node["telemetry"]["ip"] == "192.168.1.117"
        assert node["telemetry"]["board"] == "sandy-cam"


def test_all_three_boards_name_themselves_distinctly():
    """Three boards, three incompatible binaries, three distinct names.

    An IP alone does not say which board you found, and pushing brain firmware
    at the camera is not a mistake anyone notices until it stops booting. The
    names are declared in three separate files that no compiler checks against
    each other, so this is where a copy-paste collision gets caught.
    """
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    sources = {
        "brain":  root / "firmware/brain-core/main/include/config.h",
        "camera": root / "vision-core/config.h",
        "room":   root / "room-node/room-node.ino",
    }
    names = {}
    for board, path in sources.items():
        m = re.search(r'#define\s+SANDY\w*BOARD_ID\s+"([^"]+)"',
                      path.read_text(encoding="utf-8"))
        assert m, f"{board}: no board id in {path.name} — it cannot identify itself"
        names[board] = m.group(1)

    assert len(set(names.values())) == 3, f"two boards share a name: {names}"


# ── The display: free text, and a picture that must not be trusted ───────────

def test_the_display_takes_a_sentence_not_a_menu(db):
    """What goes on her face is whatever the owner typed.

    A `text` control is the one place the registry must NOT lower-case, must not
    match against a list of allowed values, and must not reformat — those are
    exactly the transformations that ruin a sentence. This pins that.
    """
    with as_tenant("owner"):
        node_store.pair_node("sandybrain01", "ساندي")
        node_store.ingest_status("sandybrain01", True, [],
                                 [{"id": "screen", "kind": "pwm"}], "0.8.0")
        dev = device_store.get_device("sandy_screen")
        assert dev is not None, "the display was declared and did not appear"

        res = device_store.command_payload(dev, "set", "Back in 10 Minutes")
        assert res["ok"] and res["payload"] == "text:Back in 10 Minutes", res

        res = device_store.command_payload(dev, "set", "برجع بعد عشر دقايق")
        assert res["ok"] and res["payload"] == "text:برجع بعد عشر دقايق", res

        # Dismissing is a word, not a special endpoint.
        assert device_store.command_payload(dev, "set", "dismiss")["payload"] == "dismiss"

        # Newlines would split the single-line MQTT payload in two.
        res = device_store.command_payload(dev, "set", "one\ntwo")
        assert "\n" not in res["payload"], res


def test_the_display_refuses_arabic_that_would_be_cut_in_half(db):
    """The board's buffer is 256 bytes and Arabic is multi-byte in UTF-8.

    Counting characters would let a 200-character Arabic line through, and the
    firmware would truncate it mid-letter — a sentence that ends in a broken
    glyph, on the device that is hardest to debug. Counting bytes refuses it
    here, where the app can say so.
    """
    with as_tenant("owner"):
        node_store.pair_node("sandybrain01", "ساندي")
        node_store.ingest_status("sandybrain01", True, [],
                                 [{"id": "screen", "kind": "pwm"}], "0.8.0")
        dev = device_store.get_device("sandy_screen")

        long_ar = "س" * 200          # 200 characters, 400 bytes
        assert len(long_ar) < 256 and len(long_ar.encode("utf-8")) > 256
        res = device_store.command_payload(dev, "set", long_ar)
        assert res["ok"] is False and res["error"] == "too_long", res

        fits = "س" * 100             # 200 bytes
        assert device_store.command_payload(dev, "set", fits)["ok"] is True


def test_a_picture_becomes_exactly_what_the_panel_draws():
    """Resized, converted, byte-ordered — and the byte order is not a detail.

    The display runs with LV_COLOR_16_SWAP, so pixels go out big-endian. Wrong,
    and the picture appears in convincing but entirely wrong colours, which
    looks like a style choice rather than a bug and survives for weeks.
    """
    from PIL import Image
    from app.features.screen_sender import IMG_BYTES, SCREEN_H, SCREEN_W, to_rgb565

    src = io.BytesIO()
    Image.new("RGB", (640, 480), (255, 0, 0)).save(src, format="PNG")
    raw = to_rgb565(src.getvalue())

    assert len(raw) == IMG_BYTES == SCREEN_W * SCREEN_H * 2
    # Pure red in RGB565 is 0xF800; big-endian that is F8 then 00.
    assert raw[0] == 0xF8 and raw[1] == 0x00, (raw[0], raw[1])


def test_a_wide_photo_is_cropped_not_squashed():
    """A face stretched to fit is worse than a face with less background."""
    from PIL import Image
    from app.features.screen_sender import SCREEN_H, SCREEN_W, to_rgb565

    src = io.BytesIO()
    img = Image.new("RGB", (900, 300), (0, 0, 0))
    # A blue band down the exact middle survives a centre crop; it would be
    # displaced by a squash.
    for x in range(440, 460):
        for y in range(300):
            img.putpixel((x, y), (0, 0, 255))
    img.save(src, format="PNG")

    raw = to_rgb565(src.getvalue())
    mid = (SCREEN_H // 2) * SCREEN_W * 2 + (SCREEN_W // 2) * 2
    pixel = (raw[mid] << 8) | raw[mid + 1]
    assert (pixel & 0x001F) > 20, f"centre is not blue: {pixel:04x}"


def test_the_camera_appears_in_the_app_like_any_other_board(db):
    """It is a different board and it needs no special case anywhere.

    It declares its outputs in a heartbeat, the catalogue says how to draw them,
    and provisioning does the rest — the same path the brain uses. The moment
    the camera needs its own branch in the provisioning logic, that logic has
    stopped being a rule and become a list.
    """
    # `cam/`-prefixed, because the camera shares a node id with the brain: it is
    # part of Sandy, not a second box. The prefix is what stops `flash` from
    # sitting beside `servo` in one list and colliding the day somebody puts a
    # flash on the brain — and it carries straight through to the topic, since
    # device_topic joins node id and output id with a slash.
    CAM_OUTPUTS = [
        {"id": "cam/flash", "kind": "relay"},
        {"id": "cam/flash_level", "kind": "pwm"},
        {"id": "cam/flash_mode", "kind": "pwm"},
        {"id": "cam/snapshot", "kind": "pwm"},
        {"id": "cam/stream", "kind": "relay"},
        {"id": "cam/framesize", "kind": "pwm"},
    ]
    with as_tenant("owner"):
        node_store.pair_node("sandycam01", "الكاميرا")
        node_store.ingest_status("sandycam01", True, [], CAM_OUTPUTS, "0.2.0",
                                 telemetry={"ip": "192.168.1.117", "board": "sandy-cam"})

        names = {d["name"] for d in device_store.list_devices()}
        assert {"cam_flash", "cam_flash_level", "cam_flash_mode",
                "cam_snapshot", "cam_stream", "cam_framesize"} <= names

        flash = device_store.get_device("cam_flash")
        assert device_store.command_payload(flash, "on")["payload"] == "on"
        # And the topic lands in the camera's branch, which is where it listens.
        assert device_store.device_topic(flash) == "sandy/node/sandycam01/cam/flash"

        size = device_store.get_device("cam_framesize")
        assert device_store.command_payload(size, "set", "VGA")["ok"] is True
        assert device_store.command_payload(size, "set", "8K")["ok"] is False


def test_the_light_offers_effects_and_still_says_when_audio_is_leaving(db):
    """The privacy states must never be dropped in favour of the pretty ones.

    White means audio is leaving this room, and somebody standing in front of
    her is entitled to read that without opening an app. Adding eleven effects
    must not quietly remove the four that mean something.
    """
    from app.features.node_provision import ROBOT_LED

    assert {"off", "idle", "listening", "talking"} <= set(ROBOT_LED)
    assert len(ROBOT_LED) > 10, "the effects did not land"

    with as_tenant("owner"):
        node_store.pair_node("sandybrain01", "ساندي")
        node_store.ingest_status("sandybrain01", True, [],
                                 [{"id": "led", "kind": "pwm"}], "0.8.0")
        led = device_store.get_device("sandy_led")
        for value in ("listening", "rainbow", "candle", "police"):
            assert device_store.command_payload(led, "set", value)["ok"] is True, value
        assert device_store.command_payload(led, "set", "disco")["ok"] is False


def test_the_app_can_draw_every_control_type_the_backend_can_create(db):
    """A control type the app has never heard of used to render as a switch.

    That is exactly what happened with the display: the backend created it as
    `text`, DeviceCard's `default:` branch drew an on/off toggle, and every tap
    sprang back because the board does not understand "on". A switch that lies
    is worse than a line admitting the app is out of date — so the fallback now
    says so, and this makes sure the list of types the app draws keeps up with
    the list the backend can produce.
    """
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    card = (root / "ios/SandyApp/Features/Control/DeviceCard.swift").read_text(encoding="utf-8")

    block = card[card.index("switch device.controlType"):]
    block = block[: block.index("}")]
    drawn = set(re.findall(r'case\s+"(\w+)":', block))
    assert len(drawn) >= 6, "the DeviceCard switch pattern stopped matching"

    from app.features.device_store import CONTROL_TYPES
    missing = set(CONTROL_TYPES) - drawn
    assert not missing, (
        f"the backend can create {sorted(missing)} and the app has no widget for "
        "them — they fall through to the default branch"
    )


def test_the_display_device_is_reachable_end_to_end(db):
    """From what the app sends to what leaves for the board.

    Three pieces have to agree and none of them compile together: the catalogue
    calls it `text`, device_store turns free text into a `text:` payload, and the
    firmware parses that prefix. This walks the whole path once.
    """
    from app.features.screen_sender import TEXT_MAX_BYTES

    with as_tenant("owner"):
        node_store.pair_node("sandybrain01", "ساندي")
        node_store.ingest_status("sandybrain01", True, [],
                                 [{"id": "screen", "kind": "pwm"}], "0.9.0")
        dev = device_store.get_device("sandy_screen")
        assert dev["control_type"] == "text"
        assert dev["meta"]["max_bytes"] == TEXT_MAX_BYTES

        payload = device_store.command_payload(dev, "set", "hello")["payload"]
        assert payload.startswith("text:")

        topic = device_store.device_topic(dev)
        assert topic == "sandy/node/sandybrain01/screen"
        assert device_store.tenant_owns_topic(topic) is True


def test_two_boards_under_one_node_id_do_not_erase_each_other(db):
    """The brain and the camera share a node id, and both send a heartbeat.

    That is deliberate — the camera is part of Sandy, not a second box — but it
    means two different heartbeats arrive five seconds apart claiming to
    describe the same node. If the camera's simply replaced `outputs`, the app
    would flicker between a robot with a neck and a robot with a flash, twice
    every ten seconds, and nobody would be able to describe the bug.

    So a camera heartbeat replaces only the `cam/` entries and leaves the rest
    alone. This runs them in both orders, because "works if the brain goes
    first" is not a property anybody can rely on over a network.
    """
    from app.integrations.mqtt_ingest import _ingest_cam_status

    BRAIN = [{"id": "servo", "kind": "servo"}, {"id": "screen", "kind": "pwm"}]
    CAM_JSON = ('{"outputs":[{"id":"flash","kind":"relay"},'
                '{"id":"snapshot","kind":"pwm"}],"ip":"192.168.1.117",'
                '"board":"sandy-cam"}')

    def outputs_now():
        return {o["id"] for o in node_store.get_node("sandy0001")["outputs"]}

    with as_tenant("owner"):
        node_store.pair_node("sandy0001", "ساندي")

        # brain first, then camera
        node_store.ingest_status("sandy0001", True, [], BRAIN, "0.9.0")
        _ingest_cam_status("sandy0001", CAM_JSON)
        assert outputs_now() == {"servo", "screen", "cam/flash", "cam/snapshot"}

        # ...and a brain heartbeat afterwards must not wipe the camera's half
        node_store.ingest_status("sandy0001", True, [], BRAIN, "0.9.0")
        after = outputs_now()
        assert {"servo", "screen"} <= after

        # camera first on a fresh node
        node_store.pair_node("sandy0002", "ساندي التانية")
        _ingest_cam_status("sandy0002", CAM_JSON)
        cam_only = {o["id"] for o in node_store.get_node("sandy0002")["outputs"]}
        assert cam_only == {"cam/flash", "cam/snapshot"}

        # and its address landed under its own key, which is how anyone finds
        # the camera at all. `cam_ip`, not `ip`: the brain owns `ip`, and a
        # single shared field flips between two boards every five seconds.
        assert node_store.get_node("sandy0002")["telemetry"]["cam_ip"] \
            == "192.168.1.117"


def test_the_two_boards_stop_erasing_each_other(db):
    """Brain and camera share a node id; each heartbeat must speak only for itself.

    This is the bug behind "the camera has no address" and "the address is fine"
    both being true minutes apart with nothing changed. Every write replaced the
    whole field, so the brain's heartbeat wiped the camera's outputs and address,
    the camera's wiped the microphone levels, and five seconds later it swapped
    back. Whatever you looked for was there about half the time.

    Ten alternating heartbeats: if the merge is wrong, one side is gone by the
    end. A single round trip would pass either way, which is why this runs ten.
    """
    from app.integrations.mqtt_ingest import _ingest_cam_status

    BRAIN = [{"id": "servo", "kind": "servo"}, {"id": "screen", "kind": "pwm"}]
    # `board` included because the real brain sends it — and the point of this
    # test is that the two boards' names stop overwriting each other too.
    BRAIN_TELEMETRY = {"mic_l": 40, "mic_r": 44, "volume": 80,
                       "ip": "192.168.1.102", "board": "sandy-brain-s3"}
    CAM_JSON = ('{"outputs":[{"id":"flash","kind":"relay"}],'
                '"ip":"192.168.1.117","board":"sandy-cam"}')

    with as_tenant("owner"):
        node_store.pair_node("sandy0001", "ساندي")

        for _ in range(5):
            node_store.ingest_status("sandy0001", True, [], BRAIN, "0.9.1",
                                     telemetry=BRAIN_TELEMETRY)
            _ingest_cam_status("sandy0001", CAM_JSON)

        node = node_store.get_node("sandy0001")
        outputs = {o["id"] for o in node["outputs"]}
        assert {"servo", "screen", "cam/flash"} <= outputs, outputs

        tele = node["telemetry"]
        # Each board's address under its own key, and the brain's readings
        # survived — that is the whole point.
        #
        # This assertion used to read `tele["ip"] == <the camera>` with a
        # comment calling it "the last one written". That was the bug written
        # down as though it were the design: one field, two boards, flipping
        # every five seconds. The live view read it and pointed at the brain
        # half the time, and the brain serves no video.
        assert tele.get("ip") == "192.168.1.102"          # the brain's, kept
        assert tele.get("cam_ip") == "192.168.1.117"      # the camera's, its own
        assert tele.get("board") == "sandy-brain-s3"
        assert tele.get("cam_board") == "sandy-cam"
        assert tele.get("mic_l") == 40 and tele.get("volume") == 80

        # ...and in the other order neither address moves.
        node_store.ingest_status("sandy0001", True, [], BRAIN, "0.9.1",
                                 telemetry=BRAIN_TELEMETRY)
        node = node_store.get_node("sandy0001")
        assert node["telemetry"]["ip"] == "192.168.1.102"
        assert node["telemetry"]["cam_ip"] == "192.168.1.117"
        assert "cam/flash" in {o["id"] for o in node["outputs"]}


def test_the_cameras_command_channel_is_not_mistaken_for_a_device(db):
    """`cam/command` is a channel, not a control, and authorising it as one
    silently refused every photo.

    send_to_topic authorises by finding a device whose transport builds the
    topic. No device produces `cam/command` — it is the camera's service channel
    — so every snapshot request was dropped at the boundary and the app reported
    that the camera might be off. Nothing had left the server.
    """
    from app.features.device_store import tenant_owns_topic

    with as_tenant("owner"):
        node_store.pair_node("sandy0001", "ساندي")
        node_store.ingest_status("sandy0001", True, [],
                                 [{"id": "cam/flash", "kind": "relay"}], "0.3.0")

        # Still false — and correctly so. The point is that nothing routes a
        # camera command through this check any more.
        assert tenant_owns_topic("sandy/node/sandy0001/cam/command") is False
        # A real control still authorises the normal way.
        assert tenant_owns_topic("sandy/node/sandy0001/cam/flash") is True


def test_the_catalogue_can_correct_a_part_after_it_exists(db):
    """A part provisioned once must not keep the wrong widget for ever.

    This is the bug behind three identical reports — "the text field never
    appeared". The display was provisioned as an on/off switch before it could
    take text. The catalogue was later corrected to `text`; the device already
    existed, so provisioning skipped it and it stayed a switch. Typing was
    impossible, and the toggle that *was* there flipped straight back.

    A widget that does not match the hardware is worse than a missing one: it
    invites you to use it and then lies about what happened.
    """
    from app.features.node_provision import provision_from_outputs

    with as_tenant("owner"):
        node_store.pair_node("sandybrain01", "ساندي")
        # A display from before the catalogue knew that this part takes text.
        device_store.add_device(
            name="sandy_screen", label="شاشة ساندي", control_type="switch",
            transport={"kind": "node", "node_id": "sandybrain01",
                       "output": "screen"},
            room="ساندي")
        assert device_store.get_device("sandy_screen")["control_type"] == "switch"

        provision_from_outputs("sandybrain01", [{"id": "screen", "kind": "pwm"}])

        after = device_store.get_device("sandy_screen")
        assert after["control_type"] == "text", (
            "the catalogue says this part takes text; the device kept the "
            "switch it was created with, so nothing could ever be typed")


def test_correcting_the_widget_leaves_the_owners_own_words_alone(db):
    """The catalogue owns what a part *is*. The owner owns what it is called."""
    from app.features.node_provision import provision_from_outputs

    with as_tenant("owner"):
        node_store.pair_node("sandybrain01", "ساندي")
        device_store.add_device(
            name="sandy_screen", label="وش ساندي الحلو", control_type="switch",
            transport={"kind": "node", "node_id": "sandybrain01",
                       "output": "screen"},
            room="غرفتي")

        provision_from_outputs("sandybrain01", [{"id": "screen", "kind": "pwm"}])

        after = device_store.get_device("sandy_screen")
        assert after["control_type"] == "text"
        assert after["label"] == "وش ساندي الحلو"
        assert after["room"] == "غرفتي"


def test_the_two_boards_do_not_overwrite_each_others_address(db):
    """One node id, two boards, one `ip` field — the live view's real bug.

    The brain and the camera share a node id by design, and telemetry merges by
    key. Both were sending `ip`, so the single field flipped between the two
    boards every five seconds. The stream view read it and pointed at the brain
    half the time — and the brain serves no video — so the live view failed
    roughly every other attempt with nothing in the pattern to explain it.

    The camera's address now lives under `cam_ip`, the same way its outputs live
    under `cam/`. Two boards under one id each write in their own space.
    """
    import json

    from app.integrations import mqtt_ingest

    with as_tenant("owner"):
        node_store.pair_node("sandybrain01", "ساندي")
        # The brain says where it is.
        node_store.ingest_status(
            "sandybrain01", True, [], [{"id": "servo", "kind": "servo"}],
            "0.9.1", telemetry={"ip": "192.168.1.50", "board": "sandy-brain-s3"})

    # Then the camera's heartbeat lands.
    mqtt_ingest._ingest_cam_status("sandybrain01", json.dumps({
        "ip": "192.168.1.77", "board": "sandy-cam",
        "outputs": [{"id": "flash", "kind": "relay"}],
    }))

    with as_tenant("owner"):
        tele = node_store.get_node("sandybrain01")["telemetry"]

    assert tele["ip"] == "192.168.1.50", "the camera overwrote the brain's address"
    assert tele["cam_ip"] == "192.168.1.77", "the camera's own address was lost"
