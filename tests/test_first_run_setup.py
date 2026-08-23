"""First-run network setup — the board raises its own access point.

The Wi-Fi name and password were compiled in. That is fine for one board on one
desk and it is not a product: every customer would need a source edit, a
toolchain and a flash, from the owner, for their house. It also had no answer at
all for the ordinary case — somebody changes their router — which the old code
met by retrying a dead network for ever, in silence.

These are source-level checks. The firmware has no test harness here, and the
things worth pinning are contracts between files that a compiler cannot see: a
window that must stay long, a radio two tasks must not fight over, and a screen
that must say something when the robot cannot reach anything.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


def test_setup_mode_exists_and_is_wired_into_boot():
    cmake = _read("firmware/brain-core/main/CMakeLists.txt")
    assert '"sandy_provision.c"' in cmake, (
        "the file exists and is not in the build — it would compile clean and "
        "never run, which is the failure this repo has already had once")

    main = _read("firmware/brain-core/main/sandy_main.c")
    assert "provision_init()" in main
    # After the radio is up: it watches for an association that never comes.
    assert main.index("wifi_sandy_start()") < main.index("provision_init()")


def test_the_window_is_long_enough_to_not_fire_on_a_slow_router():
    """A robot that goes into setup whenever the router is slow is worse than one
    that never does — the owner finds it in setup mode most mornings."""
    cfg = _read("firmware/brain-core/main/include/config.h")
    m = re.search(r"#define PROVISION_WINDOW_MS\s+(\d+)", cfg)
    assert m, "the window is gone"
    assert int(m.group(1)) >= 60_000, "short enough to fire on an ordinary reboot"


def test_the_reconnect_loop_yields_while_the_radio_is_being_driven():
    """Two tasks on one radio.

    A blind `esp_wifi_connect()` landing inside a scan or a credential test makes
    both fail, and the failure reads as a wrong password — the one wrong answer
    that sends the owner off to reset their router.
    """
    wifi = _read("firmware/brain-core/main/sandy_wifi.c")
    retry = wifi[wifi.index("_retry_task"):wifi.index("WIFI_TRY(")]
    assert "s_switching" in retry
    assert "provision_is_active()" in retry


def test_the_access_point_is_named_after_the_box_and_is_not_open():
    prov = _read("firmware/brain-core/main/sandy_provision.c")
    assert '"Sandy-%s", SANDY_PAIR_CODE' in prov, (
        "the setup network has to be identifiable from the sticker on the box")
    assert "WIFI_AUTH_WPA2_PSK" in prov, (
        "an open setup network hands anyone in range the list of networks this "
        "house can see, and a form that decides which one the robot joins")


def test_setup_mode_scans_and_therefore_keeps_the_station_alive():
    """APSTA, not AP. In plain AP mode the scan returns nothing and every choice
    fails for a reason nobody can see."""
    prov = _read("firmware/brain-core/main/sandy_provision.c")
    assert "WIFI_MODE_APSTA" in prov
    assert "esp_wifi_scan_start" in prov


def test_the_credentials_are_proven_before_they_are_kept():
    """`wifi_sandy_switch` tests, saves on success and reverts on failure. Setup
    must go through it rather than writing NVS itself — otherwise a typo is
    stored and the board reboots onto a network that does not exist."""
    prov = _read("firmware/brain-core/main/sandy_provision.c")
    assert "wifi_sandy_switch(ssid, pass)" in prov
    assert "nvs_set_str" not in prov, "setup writes credentials behind the test"


def test_the_page_answers_before_the_radio_moves():
    """The reply has to be written first.

    `wifi_sandy_switch` tears down the association the page is being served over,
    so a reply composed after it returns is one the phone never receives — the
    browser shows a failure for a setup that worked.
    """
    prov = _read("firmware/brain-core/main/sandy_provision.c")
    body = prov[prov.index("static esp_err_t provision_post"):]
    # The call, not the comment above it that explains why.
    assert body.index('reply(req, "Connecting') < body.index("wifi_sandy_switch(ssid, pass)")


def test_the_owner_is_told_on_the_robots_own_screen():
    """A robot that needs setup and says nothing is indistinguishable from a
    robot that is broken, and the owner's next move is the box, not the phone."""
    prov = _read("firmware/brain-core/main/sandy_provision.c")
    assert "screen_show_text" in prov
    assert "s_ap_ssid" in prov, "the screen has to name the network to join"


def test_form_values_are_percent_decoded():
    """Wi-Fi passwords are exactly the strings a form encodes — spaces, `+`, `&`,
    `%`. Skipping this fails on precisely the passwords people choose."""
    prov = _read("firmware/brain-core/main/sandy_provision.c")
    assert "url_decode" in prov
    assert "'+'" in prov and "'%'" in prov


def test_network_names_are_escaped_into_the_page():
    """The names on the air are written by strangers. One containing a quote
    would otherwise break out of its own tag."""
    prov = _read("firmware/brain-core/main/sandy_provision.c")
    for entity in ("&quot;", "&lt;", "&amp;"):
        assert entity in prov, f"missing {entity} escaping for scanned SSIDs"
