"""Package 21: the broker, the parts, the camera and the power.

Read from the sources, like the other firmware checks: each test names what a board
did wrong and fails if the code drifts back to it.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / "firmware" / "brain-core" / "main"
CAM = ROOT / "firmware" / "vision-core"


def _src(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _fn(src: str, sig: str) -> str:
    """Body of the function whose definition starts with `sig`."""
    start = src.index(sig)
    i = src.index("{", start)
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
    raise AssertionError(f"unbalanced braces after {sig}")


# ── D2: «take a photo» from the app was dropped as the camera's own echo ──

def test_the_camera_takes_a_snapshot_command_on_the_topic_it_subscribes_to():
    mqtt = _src(CAM / "cam_mqtt.ino")
    subscribed = re.search(r"kSimpleOutputs\[\] = \{([^}]*)\}", mqtt).group(1)
    assert '"snapshot"' in subscribed
    echo = re.search(r"if \((out == \"status\"[^)]*)\) return;", mqtt).group(1)
    assert '"snapshot"' not in echo, (
        "cam/snapshot is a command the app sends, not something the camera publishes")
    # The camera never publishes on it, so no topic is kept for it.
    assert "g_topicSnapshot" not in mqtt
    assert "TOPIC_SUFFIX_SNAPSHOT" not in _src(CAM / "config.h")


# ── D6: the app offered picture sizes the camera clips without a word ──

def test_the_app_offers_no_picture_size_past_the_cameras_largest():
    from app.features.node_provision import PART_CATALOGUE

    control = _src(CAM / "cam_control.ino")
    order = re.findall(r'\{"([\w\d]+)",\s*FRAMESIZE_(\w+)\}', control)
    assert len(order) >= 10, "the camera's size table stopped matching"
    config = _src(CAM / "config.h")
    largest = re.search(r"#define CAMERA_MAX_FRAME_SIZE\s+(\w+)", config).group(1)
    if largest == "CAMERA_DEFAULT_FRAME_SIZE":
        largest = re.search(r"#define CAMERA_DEFAULT_FRAME_SIZE\s+FRAMESIZE_(\w+)",
                            config).group(1)
    names = [name for name, _ in order]
    cap = [size for _, size in order].index(largest.removeprefix("FRAMESIZE_"))
    allowed = set(names[:cap + 1])

    offered = list(PART_CATALOGUE["cam/framesize"]["meta"]["values"])
    assert set(offered) <= allowed, (
        f"{sorted(set(offered) - allowed)} are past the camera's largest ({largest}): "
        "it clips them and the server records a size the photo never had")
    assert offered == names[:cap + 1], "every size up to the largest, smallest first"


# ── F12: the camera's instant «no» carried no request id, so the app waited forty seconds ──

def test_an_instant_refusal_names_the_request_and_says_why():
    body = _fn(_src(CAM / "cam_control.ino"), "void handleCamCommand(")
    snap = body[body.index('if (cmd == "snapshot")'):body.index('if (cmd == "burst")')]
    # Only a malformed id goes without one: the server never sent it, so nobody waits on it.
    assert snap.count('publishAck("snapshot", false') == 1 and '"bad id"' in snap, (
        "a refusal with no id is thrown away")
    assert 'refuseSnapshot(id, "camera_busy"' in snap
    assert 'refuseSnapshot(id, "too_soon"' in snap
    helper = _fn(_src(CAM / "cam_control.ino"), "static void refuseSnapshot(")
    assert '\\"id\\"' in helper and '\\"error\\"' in helper


def test_the_server_turns_an_instant_refusal_into_words(monkeypatch):
    import json

    import mongomock

    import app.db as appdb
    from app.integrations import camera_client

    appdb.configure(mongomock.MongoClient()["t"])
    try:
        for code in ("camera_busy", "too_soon"):
            camera_client.on_event("n1", json.dumps(
                {"cmd": "snapshot", "ok": False, "detail": "x", "id": f"r-{code}",
                 "error": code}))
            err = camera_client.fetch_snapshot_error("n1", f"r-{code}")
            assert err and err["error"] == code
            assert err["message"] == camera_client._ERROR_TEXT[code]
    finally:
        appdb.reset()


# ── J3: the brain heard the camera's and the room's whole branches, every few seconds ──

def test_the_brain_subscribes_one_level_under_its_id():
    mqtt = _src(MAIN / "sandy_mqtt.c")
    connected = mqtt[mqtt.index("case MQTT_EVENT_CONNECTED:"):mqtt.index("case MQTT_EVENT_SUBSCRIBED:")]
    assert 'snprintf(sub, sizeof(sub), "%s/+", s_base);' in connected, (
        "one level: the cam/ and room/ branches (heartbeats, events) stay off the robot")
    assert '"%s/#"' not in mqtt
    # Every command the brain takes is one level deep, so none is lost to the narrower filter.
    dispatch = _fn(mqtt, "static void _dispatch(")
    for out in re.findall(r'!strcmp\(out, "([^"]+)"\)\)\s+\w', dispatch):
        assert "/" not in out, f"{out} is two levels deep and the brain no longer hears it"
    # Nothing two levels deep reaches the dispatch, so it no longer checks for it.
    assert '"cam/"' not in dispatch and '"room/"' not in dispatch


# ── J7: the pairing code's timer cleared whatever was on the screen five minutes later ──

def test_the_pairing_code_timer_clears_only_its_own_code():
    screen = _src(MAIN / "sandy_screen.c")
    header = _src(MAIN / "include" / "sandy_screen.h")
    assert "uint32_t screen_shown(void);" in header
    # Every new thing on the screen moves the count, the dismiss too.
    for sig in ("void screen_show_text(", "void screen_show_qr(", "bool screen_image_end(",
                "void screen_dismiss("):
        assert "s_shown_seq++" in _fn(screen, sig), f"{sig} does not count what it shows"

    mqtt = _src(MAIN / "sandy_mqtt.c")
    expired = _fn(mqtt, "static void _pair_code_expired(")
    assert "screen_shown() == s_pair_shown" in expired and "screen_dismiss()" in expired
    shown = _fn(mqtt, "static void _handle_pair_code(")
    assert shown.index("screen_show_text(text)") < shown.index("s_pair_shown = screen_shown()")


# ── J6: a long IR code and the next one sharing one buffer ──

def test_an_ir_code_is_written_only_once_the_last_one_has_left():
    body = _fn(_src(MAIN / "sandy_ir.c"), "static void ir_send_text(")
    # The previous code is still being read out of `sym` until it is done.
    drain = body.index("rmt_tx_wait_all_done(s_tx, IR_TX_DRAIN_MS)")
    assert drain < body.index("sym[nsym]"), "the buffer is overwritten while it is still sent"
    # And the wait after a send is as long as the code, not one fixed second.
    assert "rmt_tx_wait_all_done(s_tx, 1000)" not in body
    assert "total_us" in body and "rmt_tx_wait_all_done(s_tx, wait_ms)" in body


# ── A9: the ears or the speaker test with voice took the voice's I2S and halted the boot ──

def test_the_ears_and_the_speaker_test_cannot_be_built_beside_voice_and_never_halt():
    config = _src(MAIN / "include" / "config.h")
    assert re.search(r"#if ENABLE_EARS && ENABLE_VOICE\s*\n#error", config)
    assert re.search(r"#if ENABLE_SPK_TEST && ENABLE_VOICE\s*\n#error", config)
    # Built alone, a part that will not start says so and the boot goes on (TRY_INIT).
    for name in ("sandy_ears.c", "sandy_spktest.c"):
        assert "ESP_ERROR_CHECK" not in _src(MAIN / name), f"{name} still halts the boot"


# ── B6: a brownout reset the crash count and was counted nowhere ──

def test_a_brownout_neither_counts_as_a_crash_nor_clears_the_count():
    health = _src(MAIN / "sandy_health.c")
    boot = _fn(health, "void health_boot(")
    brown = boot[boot.index("if (r == ESP_RST_BROWNOUT)"):boot.index("} else if (is_crash(r)")]
    # The owner's decision: neutral, the crash count neither moves nor clears.
    assert "s_guard.crashes" not in brown, "a brownout touched the crash count"
    # Its own count instead, in the settings store: ever, and in a row.
    count = _fn(health, "static void count_boot(")
    assert '"brownouts"' in count and '"brown_row"' in count
    assert "s_brownout_row++" in count and "HEALTH_POWER_WEAK_AFTER" in count
    assert "SANDY_PART_POWER, SANDY_ST_POWER_LOW" in count
    # A stable run ends the row, written by the monitor rather than the timer task.
    stable = _fn(health, "static void stable_cb(")
    assert "s_row_to_clear = true" in stable and "SANDY_PART_POWER, SANDY_ST_OK" in stable
    assert "clear_brownout_row()" in _fn(health, "static void monitor_task(")

    config = _src(MAIN / "include" / "config.h")
    assert re.search(r"#define HEALTH_POWER_WEAK_AFTER\s+\d", config)


def test_weak_power_is_a_status_of_its_own_and_in_the_heartbeat():
    status_h = _src(MAIN / "include" / "sandy_status.h")
    assert "SANDY_ST_POWER_LOW" in status_h and "SANDY_PART_POWER" in status_h
    table = _src(MAIN / "sandy_status.c")
    assert "[SANDY_ST_POWER_LOW]" in table and '[SANDY_PART_POWER]' in table
    assert '"power_low"' in table and '"POWER LOW"' in table

    json_fn = _fn(_src(MAIN / "sandy_health.c"), "int health_json(")
    assert '\\"brownouts\\":%lu' in json_fn and '\\"power_weak\\":%s' in json_fn
    # The health members had 640 bytes and nearly filled them; two more need room.
    cap = int(re.search(r"HEALTH_CAP = (\d+)", _src(MAIN / "sandy_mqtt.c")).group(1))
    assert cap >= 768


def test_the_server_keeps_the_brownout_count_and_weak_power(monkeypatch):
    from app.features import node_store

    kept = node_store._clean_telemetry(
        {"brownouts": 4, "power_weak": True, "faults": {"power": "power_low"}})
    assert kept["brownouts"] == 4 and kept["power_weak"] is True
    assert kept["faults"] == {"power": "power_low"}
