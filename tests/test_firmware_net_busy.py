"""An update check and a voice session never hold TLS at the same time.

Both at once ran internal RAM out and rebooted the board ("Hi Andy" during an
update check). sandy_net_busy is the one lock between them; these checks read
the sources to keep every open path claiming it and every exit releasing it.
"""

from __future__ import annotations

import re
from pathlib import Path

MAIN = Path(__file__).resolve().parent.parent / "firmware" / "brain-core" / "main"


def _src(name: str) -> str:
    return (MAIN / name).read_text(encoding="utf-8")


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


def test_the_lock_is_a_compare_and_swap_and_is_built():
    c = _src("sandy_net_busy.c")
    assert "atomic_compare_exchange_strong" in _fn(c, "bool net_claim(")
    assert "atomic_compare_exchange_strong" in _fn(c, "void net_release(")
    assert '"sandy_net_busy.c"' in _src("CMakeLists.txt")


def test_ota_check_claims_before_and_releases_after_the_check():
    body = _fn(_src("sandy_ota.c"), "static void ota_check_task(")
    claim = body.index("net_claim(NET_OWNER_OTA)")
    once = body.index("ota_check_once()")
    release = body.index("net_release(NET_OWNER_OTA)")
    assert claim < once < release
    # A skipped check comes back in minutes, not after the six-hour period.
    assert "OTA_RETRY_MS" in body and "esp_timer_start_once" in body


def test_voice_claims_before_opening_and_releases_on_every_exit():
    v = _src("sandy_voice.c")
    body = _fn(v, "static void voice_task(")

    wake = body.index("s_wake_req = false;")
    claim = body.index("net_claim(NET_OWNER_VOICE)")
    unload = body.index("s_mn_want = false;")          # the model hand-over
    opened = body.index("if (ws_open())")
    assert wake < claim < unload < opened, "claim must precede the handshake"

    # Refused (an update holds it): nothing to release, but she goes back to idle.
    refuse = body[claim:unload]
    assert "net_owner() != NET_OWNER_VOICE" in refuse and "continue;" in refuse

    # Exit 1: command model never released -> session skipped.
    skip = body[unload:opened]
    assert re.search(r"net_release\(NET_OWNER_VOICE\);\s*continue;", skip)

    # Exit 2: ws_open failed.
    failed = body[opened:body.index("} else if (s_link_lost_ms")]
    assert failed.count("net_release(NET_OWNER_VOICE)") == 1

    # Exit 3: the session closes — idle or refused — through one function that
    # gives the socket back before the claim.
    assert body.count("session_end();") == 2
    assert "ws_close();" not in body
    end = _fn(v, "static void session_end(")
    assert end.index("ws_close();") < end.index("net_release(NET_OWNER_VOICE)")

    # No other ways in or out that could leak or skip the lock.
    assert body.count("net_claim(") == 1
    assert body.count("net_release(NET_OWNER_VOICE)") == 2
