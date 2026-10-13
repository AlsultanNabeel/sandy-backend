"""The rescue commands work on a robot in safe mode, and broker credentials are kept only
once they work (package 19). These read the sources, since the boards cannot run here.

In safe mode only Wi-Fi, OTA and MQTT start, and the MQTT side takes three commands:
`wifi`, `ota` and `factory_reset`. The erase is signed with the board's own key and checked
against the wall clock, and both the key and the clock lived inside the voice task, which
safe mode never starts: a robot that crashed its way into safe mode could not be wiped.
"""
from __future__ import annotations

import re
from pathlib import Path

MAIN = Path(__file__).resolve().parent.parent / "firmware" / "brain-core" / "main"


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


def _app_main() -> str:
    return _block(_src("sandy_main.c"), "void app_main(")


# ── F2: the board's own key ──

def test_the_own_key_is_loaded_at_boot_before_mqtt_and_outside_safe_mode():
    main = _app_main()
    load = main.index("voice_key_init();")
    assert main.index('identity_init()') < load < main.index("_mqtt_late_start")
    # Not inside the `if (safe)` / `if (!safe)` branches.
    assert load < main.index("if (safe)")
    assert "voice_key_init();" not in _block(_src("sandy_voice.c"), "static void voice_task(")
    assert "void voice_key_init(void);" in _src("include/sandy_voice.h")


# ── J1: the clock ──

def test_the_clock_is_started_by_app_main_in_every_mode_not_by_the_voice_task():
    main = _app_main()
    loop = _block(main, "for (;;)")
    assert "clock_poll();" in loop                    # after both branches, safe mode too
    clock = _src("sandy_clock.c")
    assert "esp_netif_sntp_init" in clock
    poll = _block(clock, "void clock_poll(")
    assert "wifi_sandy_is_connected()" in poll and "start()" in poll
    voice = _src("sandy_voice.c")
    assert "esp_netif_sntp" not in voice and "clock_start(" not in voice
    assert '"sandy_clock.c"' in _src("CMakeLists.txt")


def test_a_replay_refusal_still_resyncs_the_clock():
    voice = _src("sandy_voice.c")
    assert "clock_refuse();" in voice
    assert "clock_resync();" in _block(voice, "static void clock_tick(")
