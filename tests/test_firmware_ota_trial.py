"""An update on trial is remembered until it is confirmed, on all three boards.

A new image used to clear its own "trying" note the moment it booted. When its trial
then failed and the bootloader went back to the old image, the old one found no note,
did not count the failure, and took the same release again a minute later: a reboot
and download loop across the fleet. These checks read the sources, since the boards
cannot run here.
"""

from __future__ import annotations

from pathlib import Path

FIRMWARE = Path(__file__).resolve().parent.parent / "firmware"
BRAIN = FIRMWARE / "brain-core" / "main"


def _src(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _block(src: str, sig: str) -> str:
    """The braces block that opens after `sig`."""
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


# ── The brain ──

def test_the_brain_keeps_its_own_trial_note_at_boot():
    body = _block(_src(BRAIN / "sandy_ota.c"), "static void ota_nvs_check_last_try(")
    failed = _block(body, "strcmp(trying, SANDY_FW_VERSION) != 0")
    assert 'nvs_erase_key(h, "trying")' in failed
    # Outside the "another version failed" branch, nothing clears the note.
    assert 'nvs_erase_key(h, "trying")' not in body.replace(failed, "")


def test_the_brain_clears_the_note_only_when_its_image_is_confirmed():
    src = _src(BRAIN / "sandy_ota.c")
    confirmed = _block(src, "static void ota_confirmed(")
    assert "s_confirmed = true;" in confirmed
    assert "ota_nvs_drop_trying(SANDY_FW_VERSION)" in confirmed
    # Every way to "confirmed" goes through it.
    assert src.count("s_confirmed = true;") == 1
    drop = _block(src, "static void ota_nvs_drop_trying(")
    assert "strcmp(trying, version) == 0" in drop   # never another version's note


def test_the_brain_notes_the_version_before_it_switches_the_boot_slot():
    body = _block(_src(BRAIN / "sandy_ota.c"), "static ota_result_t ota_check_once(")
    note = body.index("ota_nvs_note_trying(version)")
    switch = body.index("esp_ota_set_boot_partition(slot)")
    assert note < switch < body.index("esp_restart()")
    # A switch that failed leaves no note behind to be counted as a failed trial.
    assert "ota_nvs_drop_trying(version)" in body[switch:]


# ── The camera and the room node (one updater, kept identical) ──

SMALL = FIRMWARE / "vision-core" / "sandy_ota_pull.h"


def test_the_small_boards_share_one_updater():
    assert _src(SMALL) == _src(FIRMWARE / "room-node" / "sandy_ota_pull.h")


def test_a_small_board_keeps_its_own_trial_note_at_boot():
    begin = _block(_src(SMALL), "static void sandyOtaBegin(")
    failed = _block(begin, "trying != cfg.version")
    assert 'p.remove("trying")' in failed
    assert 'p.remove("trying")' not in begin.replace(failed, "")
    # Only an image that is not on trial drops a note naming itself.
    assert "if (!g_otaPendingVerify) sandyOtaDropTrying(cfg.version);" in begin


def test_a_small_board_clears_the_note_only_when_its_image_holds():
    src = _src(SMALL)
    loop = _block(src, "static void sandyOtaLoop(")
    valid = loop.index("esp_ota_mark_app_valid_cancel_rollback()")
    assert loop.index("sandyOtaDropTrying(g_otaCfg.version)") > valid
    drop = _block(src, "static void sandyOtaDropTrying(")
    assert '== version) p.remove("trying")' in drop


def test_a_small_board_notes_the_version_before_it_switches():
    body = _block(_src(SMALL), "static unsigned long sandyOtaCheckOnce(")
    note = body.index("sandyOtaNoteTrying(version)")
    switch = body.index("Update.end(true)")   # this is what sets the boot slot
    assert note < switch < body.index("ESP.restart()")
    assert "sandyOtaDropTrying(version)" in body[switch:]


# ── A call during the brain's trial ──

def test_a_call_is_not_counted_against_the_trial_and_is_never_cut_by_a_rollback():
    body = _block(_src(BRAIN / "sandy_ota.c"), "static void _health_task(")
    assert "const bool in_call = net_owner() == NET_OWNER_VOICE;" in body
    assert "if (in_call) call_ms += now - last;" in body
    assert "now - start - call_ms" in body
    rollbacks = [i for i in range(len(body)) if body.startswith("_roll_back(", i)]
    assert len(rollbacks) == 2
    for at in rollbacks:
        cond = body[body.rindex("if (", 0, at):at]
        assert "!in_call" in cond, f"a rollback with a call on: {cond!r}"
        assert "trial_ms" in cond, f"a deadline that counts the call: {cond!r}"
    # The server is not asked while a call holds the network.
    ask = body.index("ota_server_answers()")
    assert "!in_call" in body[body.rindex("if (", 0, body.rindex("if (", 0, ask)):ask]


# ── The small boards' watchdog through an update check ──

def test_a_small_board_feeds_its_watchdog_around_every_network_step():
    src = _src(SMALL)
    get = _block(src, "static int sandyOtaGet(")
    # Before the connect, after it, after the status line, after each header line.
    connect = get.index("c.connect(")
    assert get.rindex("sandyOtaFeed();", 0, connect) < connect
    assert get.index("sandyOtaFeed();", connect) < get.index("c.print(")
    first = get.index("readStringUntil")
    assert get.index("sandyOtaFeed();", first) < get.index("while (c.connected()")
    headers = _block(get, "while (c.connected() || c.available())")
    assert headers.index("sandyOtaFeed();") > headers.index("readStringUntil")
    check = _block(src, "static unsigned long sandyOtaCheckOnce(")
    manifest = _block(check, "while ((long)js.length() < len")
    assert "sandyOtaFeed();" in manifest
    assert "g_otaCfg.feed" not in check            # one way to feed, through sandyOtaFeed


def test_every_step_of_a_check_has_a_deadline_under_the_shortest_watchdog():
    import re

    src = _src(SMALL)
    connect = int(re.search(r"#define SANDY_OTA_CONNECT_TIMEOUT_MS\s+(\d+)", src).group(1))
    read = int(re.search(r"#define SANDY_OTA_NET_TIMEOUT_MS\s+(\d+)", src).group(1))
    room = _src(FIRMWARE / "room-node" / "room-node.ino")
    watchdog = int(re.search(r"#define ROOM_WDT_TIMEOUT_MS\s+(\d+)", room).group(1))
    # The connect is a TCP connect and a TLS handshake, each with this deadline.
    assert 2 * connect < watchdog and read < watchdog
    get = _block(src, "static int sandyOtaGet(")
    assert "c.connect(g_otaCfg.host, 443, SANDY_OTA_CONNECT_TIMEOUT_MS)" in get
    assert "c.setHandshakeTimeout(SANDY_OTA_CONNECT_TIMEOUT_MS / 1000)" in get


def test_a_small_board_checks_in_the_pass_after_the_one_that_reached_the_broker():
    loop = _block(_src(SMALL), "static void sandyOtaLoop(")
    assert "const bool justOnline = online && !g_otaOnlineLastPass;" in loop
    check = loop.index("sandyOtaCheckOnce()")
    assert "justOnline" in loop[loop.rindex("if (!online", 0, check):check]
