"""The brain's second pass: identity out of the image, updates on trial, a
broker link that says when it is gone, and a voice link that fails closed.

Structural on purpose — the firmware builds with ESP-IDF, not here — so each
test pins the one line whose absence was the bug.
"""
from __future__ import annotations

import re
from pathlib import Path

MAIN = Path(__file__).resolve().parent.parent / "firmware" / "brain-core" / "main"
FW = MAIN.parent


def _src(name: str) -> str:
    return (MAIN / name).read_text(encoding="utf-8")


def test_only_the_identity_module_reads_secrets():
    """One image goes to every robot, so no other file may bake in who it is."""
    for f in MAIN.glob("*.c"):
        if f.name == "sandy_identity.c":
            continue
        assert '#include "secrets.h"' not in f.read_text(encoding="utf-8"), f.name
    ident = _src("sandy_identity.c")
    assert '#if SANDY_RETAIL\n#include "secrets.example.h"' in ident
    example = _src("secrets.example.h")
    assert '#define SANDY_PAIR_CODE     "SANDY-XXXX"' in example
    assert '"YOUR_' in example


def test_the_factory_partition_and_the_bigger_slots_exist():
    table = (FW / "partitions.csv").read_text()
    rows = {r.split(",")[0].strip(): [c.strip() for c in r.split(",")]
            for r in table.splitlines() if r.strip() and not r.startswith("#")}
    assert rows["nvs"][3] == "0x9000", "moving NVS wipes every saved setting"
    assert int(rows["ota_0"][4], 16) == int(rows["ota_1"][4], 16) == 0x400000
    assert rows["fctry"][1:3] == ["data", "nvs"]
    assert rows["coredump"][2] == "coredump"
    assert '"fctry"' in _src("sandy_identity.c")


def test_an_update_stays_on_trial_until_the_server_answers():
    ota = _src("sandy_ota.c")
    assert "OTA_HEALTH_STABLE_MS" in ota and "ota_server_answers()" in ota
    assert "ota_version_is_bad(version)" in ota, "a failed release was retried forever"
    assert "ota_nvs_note_trying(version)" in ota
    assert "atomic_exchange(&s_ota_running, true)" in ota
    assert "if (!s_confirmed)" in ota, "an image on trial must not install another"


def test_the_broker_link_has_a_will_a_backoff_and_ignores_stale_commands():
    mq = _src("sandy_mqtt.c")
    assert ".last_will" in mq and '"{\\"online\\":false}"' in mq
    assert ".disable_auto_reconnect = true" in mq and "esp_random()" in mq
    assert "retained && _is_one_shot(out)" in mq
    for one_shot in ("factory_reset", "wifi", "ota"):
        assert f'!strcmp(out, "{one_shot}")' in mq
    # The boot chime is app_main's; a reconnect is not a boot.
    connected = mq[mq.index("case MQTT_EVENT_CONNECTED"):mq.index("case MQTT_EVENT_SUBSCRIBED")]
    assert "MELODY_BOOT" not in connected
    # A new credential waits for the call to end (two TLS handshakes at once
    # rebooted the board).
    assert "s_creds_pending = true;" in mq and "voice_is_connected()" in mq


def test_voice_fails_closed_and_writes_the_speaker_one_at_a_time():
    v = _src("sandy_voice.c")
    assert "voice stays always-on" not in v, "no wake word must not mean an open microphone"
    assert "s_spk_wr_lock" in v and v.count("xSemaphoreTake(s_spk_wr_lock") == 2
    assert "esp_websocket_client_close(" in v, "the server should hear the call end"
    assert "mbedtls_platform_zeroize(own" in v
    assert "portMAX_DELAY);\n        ESP_LOGI(TAG, \"connected, sent hello\")" not in v
    assert "s_auth_refused" in v and "VOICE_AUTH_BACKOFF_MS" in v
    # Noise suppression never runs before the echo canceller.
    mic = v[v.index("static void mic_task("):]
    assert mic.index("aec_process(") < mic.index("ns_clean(")


def test_local_sounds_play_at_her_rate():
    ctl = _src("sandy_audio_ctl.c")
    assert re.search(r"const int SR = VOICE_OUT_RATE", ctl), "tones were 16 kHz in a 24 kHz buffer"


def test_wifi_says_wrong_password_and_setup_keeps_trying_home():
    w = _src("sandy_wifi.c")
    assert "WIFI_REASON_4WAY_HANDSHAKE_TIMEOUT" in w and "SANDY_ST_WIFI_BAD_PASS" in _src("sandy_voice.c")
    assert "xEventGroupClearBits(s_eg, WIFI_CONNECTED_BIT);\n    s_ip[0]" in w, (
        "the switch saw the OLD link's connected bit and saved an untested password")
    prov = _src("sandy_provision.c")
    assert "(password '%s')" not in prov, "the setup password was in the log"


def test_the_neck_restores_where_it_was_and_lets_go_when_idle():
    servo = _src("sandy_servo.c")
    init = servo[servo.index("esp_err_t servo_init(void)"):]
    # The saved angle is read before the channel exists, and the channel starts there.
    assert init.index("nvs_load_servo_angle") < init.index("ledc_channel_config")
    assert ".duty       = _angle_to_duty(saved)" in servo
    assert "_relax()" in servo and "SERVO_RELAX_MS" in _src("include/config.h")


def test_the_privacy_light_follows_the_microphone_not_the_last_request():
    led = _src("sandy_led.c")
    assert "voice_session_is_active()" in led
    assert "if (s_state_owns || session_live())" in led
    # A colour-less effect keeps the owner's colour; gestures no longer paint black.
    assert "LED_RGB_KEEP" in led and "led_set_effect(s->fx, LED_RGB_KEEP, 5)" in _src("sandy_mqtt.c")
    assert "t * t / steps / steps" not in led, "the sunrise's blue was integer zero"


def test_ir_learning_ends_and_long_codes_fit():
    ir = _src("sandy_ir.c")
    assert "IR_LEARN_TIMEOUT_MS" in ir and "IR_MAX_TICKS" in ir
    assert ".flags.with_dma    = true" in ir


def test_the_face_survives_a_failed_flush_and_keeps_the_banner_on_top():
    face = _src("sandy_face.c")
    assert "lv_disp_flush_ready(drv);" in face[face.index("static void _flush_cb"):]
    assert "lv_obj_move_foreground(s_banner)" in face
    assert "if (!s_ready ||" in face
    assert "face_set_mood_from_app(" in _src("sandy_mqtt.c")
    for touch in ("breathe_timer_cb", "lipsync_timer_cb", "backlight_step", "MOOD_THINKING"):
        assert touch in face, touch


def test_a_picture_is_swapped_in_whole():
    scr = _src("sandy_screen.c")
    assert "s_img_rx" in scr and "s_rx_bytes == IMG_BYTES" in scr
    assert "screen_show_qr(qr, msg)" in _src("sandy_provision.c")
    assert "CONFIG_LV_USE_QRCODE=y" in (FW / "sdkconfig.defaults").read_text()
