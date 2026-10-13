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
    assert "PROVISION_RETRY_MS" in task and "start_ap()" in task


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
