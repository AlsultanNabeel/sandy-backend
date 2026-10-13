"""An update on trial is remembered until it is confirmed.

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


# ── Settings saved before every restart ──

def test_every_brain_restart_saves_the_deferred_settings_first():
    """A volume or neck change waits a few seconds before it is written; a restart
    that does not write it first loses it. The factory reset is the one exception:
    it has just erased the store."""
    import re

    restart = re.compile(r"\besp_restart\(\);|esp_ota_mark_app_invalid_rollback_and_reboot\(\);")
    checked = 0
    for path in sorted(BRAIN.glob("*.c")):
        src = _src(path)
        for m in restart.finditer(src):
            fn_start = src.rindex("\n}", 0, m.start())   # the end of the function before
            before = src[fn_start:m.start()]
            if "nvs_flash_erase()" in before:
                continue
            assert "nvs_flush_deferred();" in before, f"{path.name}: a restart that drops settings"
            checked += 1
    assert checked >= 4   # install, rollback, setup, health_restart (and the dev upload)
