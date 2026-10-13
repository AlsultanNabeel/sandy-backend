"""Moving a board between networks and its setup network (package 20). These read the
sources, since the boards cannot run here.

The setup network is the last way back to a board whose network is gone, so everything
here is about it coming up when it should, being usable when it does, and a switch
never leaving a board on a network it cannot use.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / "firmware" / "brain-core" / "main"


def _src(name: str) -> str:
    return (MAIN / name).read_text(encoding="utf-8")


def _block(src: str, sig: str) -> str:
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


# ── B3: the owner's build holds port 80 for the LAN upload ──

def test_the_setup_page_takes_port_80_from_the_upload_server_and_gives_it_back():
    prov = _src("sandy_provision.c")
    start = _block(prov, "static bool start_ap(")
    assert start.index("remote_http_release();") < start.index("httpd_start(")
    stop = _block(prov, "static void stop_ap(")
    assert "remote_http_resume();" in stop
    remote = _src("sandy_remote.c")
    assert "void remote_http_release(void)" in remote and "void remote_http_resume(void)" in remote
    header = (MAIN / "include" / "sandy_remote.h").read_text(encoding="utf-8")
    assert "remote_http_release" in header and "remote_http_resume" in header


def test_the_radio_moves_only_once_the_page_is_up():
    start = _block(_src("sandy_provision.c"), "static bool start_ap(")
    assert start.index("httpd_start(") < start.index("esp_wifi_set_mode(WIFI_MODE_APSTA)")
    failed = start[start.index("httpd_start("):start.index("esp_wifi_set_mode(WIFI_MODE_APSTA)")]
    assert "return false;" in failed


def test_a_page_that_cannot_start_is_retried_slowly_not_every_half_second():
    task = _block(_src("sandy_provision.c"), "static void provision_task(")
    assert "PROVISION_RETRY_MS" in task and "start_ap(" in task


# ── B4: in safe mode the setup network's password is only on her face ──

def test_safe_mode_starts_the_face_when_the_setup_network_comes_up():
    start = _block(_src("sandy_provision.c"), "static bool start_ap(")
    wake = start.index("setup_face_on();")
    assert wake < start.index("screen_show_qr(")
    on = _block(_src("sandy_provision.c"), "static void setup_face_on(")
    assert "health_safe_mode()" in on and "face_init()" in on
    # Only then: safe mode still boots without the face.
    main = _block(_src("sandy_main.c"), "void app_main(")
    assert "face_init()" not in main[:main.index("} else {")]


# ── D3: two «Connect» presses on the camera's setup page ──

CAM = ROOT / "firmware" / "vision-core"


def _cam(name: str) -> str:
    return (CAM / name).read_text(encoding="utf-8")


def test_the_camera_switches_on_its_own_copy_and_takes_no_second_request_meanwhile():
    tick = _block(_cam("cam_mqtt.ino"), "void camWifiTick(")
    # Copied before the switch, which holds them for half a minute.
    assert "camSwitchNetwork(g_wifiSsid" not in tick
    copy = tick.index("String ssid = g_wifiSsid")
    assert copy < tick.index("camSwitchNetwork(")
    # The request stays taken until the switch is over, so a second one is refused.
    assert tick.index("camSwitchNetwork(") < tick.index("g_wifiPending = false")
    queue = _block(_cam("cam_mqtt.ino"), "bool camQueueWifi(")
    assert "if (g_wifiPending) return false;" in queue


# ── D7: the camera's setup page listed no networks ──

def test_the_camera_scans_with_the_station_held_and_again_for_each_page():
    scan = _block(_cam("cam_setup.ino"), "static void setupScan(")
    # The station's connect attempt makes a scan fail: hold it, then retry once on a failure.
    assert scan.index("g_wifiHold = true") < scan.index("WiFi.scanNetworks(")
    assert "WiFi.disconnect(" in scan and scan.count("WiFi.scanNetworks(") == 2
    assert "g_wifiHold = false" in scan
    ensure = _block(_cam("cam_wifi.ino"), "void ensureWiFiConnected(")
    assert "g_wifiHold" in ensure
    # Every opening of the page asks for a fresh list.
    get = _block(_cam("cam_setup.ino"), "static esp_err_t setupRootGet(")
    assert "g_setupScanWanted = true" in get
    tick = _block(_cam("cam_setup.ino"), "void camSetupTick(")
    assert "g_setupScanWanted" in tick and "setupScan()" in tick


# ── F21: a network with an address and no internet ──

def test_a_switch_is_kept_only_once_sandys_server_answers_through_it():
    switch = _block(_src("sandy_wifi.c"), "wifi_switch_result_t wifi_sandy_switch(")
    got_ip = switch.index("wifi_sandy_ip()[0]")
    probe = switch.index("reach_probe()")
    save = switch.index("nvs_set_str(h, K_SSID, ssid)")
    assert got_ip < probe < save
    # A fresh connection only: the old network's broker session can look alive a while.
    assert "reach_last_ms()" not in switch
    assert "WIFI_SWITCH_NO_SERVER" in switch
    reach = _src("sandy_reach.c")
    probe_fn = _block(reach, "reach_t reach_probe(")
    assert "esp_crt_bundle_attach" in probe_fn and "/health" in probe_fn
    assert "net_claim(" in probe_fn and "net_release(" in probe_fn
    assert '"sandy_reach.c"' in _src("CMakeLists.txt")


def test_the_broker_a_call_and_an_update_mark_the_server_as_reached():
    assert "reach_mark();" in _block(_src("sandy_mqtt.c"), "static void _status_task(")
    voice = _src("sandy_voice.c")
    auth = voice[voice.index('if (text_has(msg, len, "auth_ok"))'):]
    assert "reach_mark();" in auth[:auth.index("}")]
    assert "reach_mark();" in _block(_src("sandy_ota.c"), "static bool ota_server_answers(void) {")


def test_the_setup_network_comes_up_after_ten_minutes_with_no_server_and_goes_with_it():
    config = (MAIN / "include" / "config.h").read_text(encoding="utf-8")
    assert "#define PROVISION_NO_SERVER_MS (10 * 60 * 1000)" in config
    task = _block(_src("sandy_provision.c"), "static void provision_task(")
    up = task[task.index("if (wifi_sandy_is_connected())"):task.index("continue;")]
    assert "PROVISION_NO_SERVER_MS" in up and "reach_probe()" in up
    assert "start_ap(true)" in up and "stop_ap()" in up


def test_the_camera_also_keeps_a_network_only_once_its_broker_answers_through_it():
    switch = _block(_cam("cam_wifi.ino"), "bool camSwitchNetwork(")
    got_ip = switch.index("WiFi.localIP() != IPAddress(0, 0, 0, 0)")
    probe = switch.index("camBrokerReachable()")
    save = switch.index("p.putString(WIFI_K_SSID, ssid)")
    assert got_ip < probe < save and "CAM_REACH_WINDOW_MS" in switch
    reach = _block(_cam("cam_wifi.ino"), "bool camBrokerReachable(")
    assert "hostByName" in reach and "connect(" in reach


def test_the_cameras_setup_network_comes_up_after_ten_minutes_with_no_broker():
    tick = _block(_cam("cam_setup.ino"), "void camSetupTick(")
    up = tick[tick.index("if (WiFi.status() == WL_CONNECTED)"):]
    assert "CAM_SETUP_NO_SERVER_MS" in up and "camBrokerReachable()" in up
    assert "mqttIsConnected()" in up and "setupStart(true)" in up


# ── The Wi-Fi command is signed and its password sealed (decision, group P2) ──

def test_the_brain_takes_only_a_signed_fresh_unseen_wifi_command():
    mqtt = _src("sandy_mqtt.c")
    handle = _block(mqtt, "static void _handle_wifi(")
    assert 'strncmp(val, "wifi:", 5)' in handle and "strchr(val, '\\n')" not in handle
    order = ["clock not set", "WIFI_CMD_WINDOW_MS", "ms <= s_wifi_last_ms",
             "voice_verify_signed(msg, f[3])", "s_wifi_last_ms = ms", "xTaskCreate(_wifi_switch_task"]
    at = [handle.index(k) for k in order]
    assert at == sorted(at)
    # The same texts the server signs and seals (wifi_switch._signed_command).
    assert '"wifi|%s|%.*s|%.*s|%.*s"' in handle and '"wifi-pass|%s|%.*s|%d"' in handle
    # Safe mode still takes it: a rescue command.
    dispatch = _block(mqtt, "static void _dispatch(")
    assert 'strcmp(out, "wifi")' in dispatch[:dispatch.index("safe mode — ignoring")]


def test_the_camera_takes_only_a_signed_fresh_unseen_wifi_command_under_its_own_id():
    mqtt = _block(_cam("cam_mqtt.ino"), "static void mqttCallback(")
    assert "handleCamWifiCommand(value)" in mqtt and "indexOf('\\n')" not in mqtt
    handle = _block(_cam("cam_wifi.ino"), "void handleCamWifiCommand(")
    order = ["CAM_CLOCK_SANE_EPOCH", "CAM_WIFI_CMD_WINDOW_MS", "signedAt <= g_wifiLastMs",
             'hmacHex(String("wifi|")', "camQueueWifi("]
    at = [handle.index(k) for k in order]
    assert at == sorted(at)
    assert 'camNodeId() + ":cam"' in handle and 'String("wifi-pass|")' in handle


def test_the_versions_the_server_signs_for_are_the_ones_built_here():
    import re

    from app.features.wifi_switch import SIGNED_FROM
    from app.features.firmware_store import version_key
    brain = re.search(r'SANDY_FW_VERSION "([^"]+)"',
                      (MAIN / "include" / "config.h").read_text()).group(1)
    cam = re.search(r'SANDY_CAM_FW_VERSION\s+"([^"]+)"', _cam("config.h")).group(1)
    assert version_key(brain) >= version_key(SIGNED_FROM["brain"])
    assert version_key(cam) >= version_key(SIGNED_FROM["camera"])
