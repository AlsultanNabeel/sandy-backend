"""The body reacts: a gesture is face, sound and light, and a scene moves the room.

The privacy light outranks any reaction, and a scene goes through the same
validation gate as a single device.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cloud"))

_ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


def test_a_gesture_moves_more_than_the_neck():
    """The owner's own example: 'dance' with a blank face and no sound.

    Every part existed — playful face, celebrate melody, party lights — and the
    handler called the servo alone. It read as a fault rather than a dance.
    """
    src = _read("firmware/brain-core/main/sandy_mqtt.c")
    assert "gesture_scene_t" in src, "a gesture drives the neck alone again"
    assert "MOOD_PLAYFUL" in src and "LED_FX_PARTY" in src, (
        "dance no longer reaches the face and the lights")
    assert "MOOD_COUNT" in src, (
        "there is no way to say 'this gesture is silent' — 'look left' should "
        "not play a tune")


def test_the_privacy_light_still_outranks_a_celebration():
    """A party must not be able to hide a live microphone.

    `led_set_effect` returns false during a voice session and the board keeps
    the indicator. That ordering is the whole guarantee, so it is asserted here
    rather than trusted.
    """
    src = _read("firmware/brain-core/main/sandy_mqtt.c")
    i_led = src.index("led_set_effect(s->fx")
    i_mood = src.index("face_set_mood(s->mood")
    assert i_mood < i_led, (
        "the light is set before the face — the visible ordering of a reaction "
        "changed, and the privacy layering comment no longer describes it")


def test_a_scene_actually_switches_something_on():
    """It used to return a list and say 'done'.

    The docstring said it outright: no hardware is actuated. So "شغّلي مشهد
    الدراسة" answered "تمام" and nothing in the room moved — a success message
    for an event that never happened, which is the worst failure a system can
    report.
    """
    src = _read("cloud/app/features/scene_store.py")
    assert "_actuate(" in src, "scenes are data again and turn nothing on"
    assert "command_payload(" in src, (
        "the scene path bypasses the validation gate that the device tool uses "
        "— two doors onto the same hardware will disagree eventually")
    assert '"missed"' in src, (
        "a scene naming a device the owner does not have now fails silently, "
        "and he has no way to learn why nothing happened")
