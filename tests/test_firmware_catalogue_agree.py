"""Every value the app can send must be a value a board understands.

The catalogue (`node_provision.PART_CATALOGUE`) decides what the app offers.
The firmware decides what it accepts. They live in different languages, in
different repositories' worth of code, and nothing compiles them together — so
when they drift, the symptom is a control in the app that silently does nothing.
Silently, because an unknown value is logged on a board nobody is watching.

This is the seam, and it now has a test.

A note on the regexes below, because getting them wrong wastes more time than
the drift they look for. An ad-hoc version of this check reported ten gestures
and one mood as missing; all eleven were present. The gestures were spelled
`GESTURE_NOD` and the pattern looked for `GEST_`, and the mood was written
`{"disappointed",MOOD_DISAPPOINTED}` with no space after the comma while the
pattern demanded one. A check that cries wolf is worse than no check, so these
are written to match the source as it is and asserted to find a plausible
minimum number of entries — if a regex stops matching, that fails too, instead
of quietly reporting an empty firmware and a fully-drifted catalogue.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "cloud"))

from app.features.node_provision import PART_CATALOGUE  # noqa: E402


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


BRAIN_MQTT = "firmware/brain-core/main/sandy_mqtt.c"
BRAIN_LED = "firmware/brain-core/main/sandy_led.c"
CAM_CONTROL = "vision-core/cam_control.ino"

# output id -> (names the firmware accepts, minimum we expect to find)
CASES = {
    "mood": (
        lambda: set(re.findall(r'\{"(\w+)",\s*MOOD_\w+\}', _read(BRAIN_MQTT))),
        20,
    ),
    "gesture": (
        lambda: set(re.findall(r'\{"(\w+)",\s*GESTURE_\w+\}', _read(BRAIN_MQTT))),
        8,
    ),
    "buzzer": (
        lambda: set(re.findall(r'!strcmp\(val,\s*"(\w+)"\)\)\s*buzzer_play', _read(BRAIN_MQTT))),
        15,
    ),
    "speaker_test": (
        lambda: set(re.findall(r'!strcmp\(val,\s*"(\w+)"\)\)\s*spk_play', _read(BRAIN_MQTT))),
        5,
    ),
    "led": (
        # The four privacy states are handled before the effect table, by name.
        lambda: (set(re.findall(r'\{"(\w+)",\s*LED_FX_\w+\}', _read(BRAIN_LED)))
                 | {"idle", "listening", "talking", "off"}),
        12,
    ),
    "framesize": (
        lambda: set(re.findall(r'\{"([\w\d]+)",\s*FRAMESIZE_\w+\}', _read(CAM_CONTROL))),
        10,
    ),
}


@pytest.mark.parametrize("output", sorted(CASES))
def test_the_app_never_offers_a_value_the_board_will_ignore(output):
    accepted_fn, minimum = CASES[output]
    accepted = accepted_fn()

    assert len(accepted) >= minimum, (
        f"only {len(accepted)} names found in the firmware for '{output}' — the "
        "pattern has stopped matching the source, so this test is not checking "
        "anything. Fix the regex before trusting the result."
    )

    offered = {str(v) for v in PART_CATALOGUE[output]["meta"]["values"]}
    unknown = offered - accepted
    assert not unknown, (
        f"the app offers {sorted(unknown)} for '{output}' and no board accepts "
        "them — they appear as working controls that do nothing"
    )


def test_every_output_the_brain_declares_has_somewhere_to_appear():
    """A part the board announces and the catalogue has no entry for is invisible.

    Not an error — a newer firmware may declare parts this backend has not
    learned yet, and provisioning deliberately ignores those. But between two
    files in the same commit it is a mistake, and this is where it shows up.
    """
    src = _read(BRAIN_MQTT)
    block = src[src.index("OUTPUTS_JSON ="):]
    block = block[: block.index('"]";')]
    declared = set(re.findall(r'\\"id\\":\\"(\w+)\\"', block))

    assert len(declared) >= 10, "the OUTPUTS_JSON pattern stopped matching"
    missing = declared - set(PART_CATALOGUE)
    assert not missing, (
        f"the brain declares {sorted(missing)} and the catalogue cannot draw "
        "them — they will not appear in the app at all"
    )
