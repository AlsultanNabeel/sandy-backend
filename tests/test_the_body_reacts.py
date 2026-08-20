"""Sandy had two halves that were never introduced.

The **life** half — tasks, focus, goals, habits, brainstorm — wrote to a
database and returned a sentence. The **body** half — twenty-five faces,
fourteen melodies, fifteen light effects — sat on the board waiting.

Nobody called it. Finishing a goal she had tracked for a month produced the word
"مبروك" and total silence, while MOOD_BIG_HAPPY, MELODY_CELEBRATE and
LED_FX_PARTY were implemented, tested and idle two metres away. Same for a focus
session: `MELODY_FOCUS_START` has existed on the board since the beginning and
had never once been played.

Not missing features. Two finished features with no wire between them.

These tests are that wire, held in place.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cloud"))

_ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


def test_there_is_one_place_that_decides_what_reacting_looks_like():
    """Callers name the moment, not the parts.

    If every feature picked its own face and melody, "celebrating" would mean
    six different things and she would stop having one personality. A tool says
    `celebrate()`; what that looks like is decided once.
    """
    from app.features import robot_expression

    for moment in ("celebrate", "focus_begin", "focus_end", "notify",
                   "acknowledge", "thinking"):
        assert hasattr(robot_expression, moment), f"{moment} is gone"


def test_a_robot_that_is_off_never_breaks_a_feature():
    """The expression is the celebration, not the achievement.

    An unplugged robot, a phone-only account, a board on another network — none
    of them may stop a reminder from being saved. Every path here fails quietly
    and returns.
    """
    src = _read("cloud/app/features/robot_expression.py")
    assert "def _node_id()" in src and "return None" in src, (
        "no path for a user with no hardware")
    assert src.count("except Exception") == 1, (
        "either an offline robot can now raise into the caller — a light "
        "failing must never lose a task — or the guard has been spread across "
        "the helpers again, which hides real bugs along with the expected ones. "
        "One catch, at the edge.")


def test_finishing_a_goal_actually_celebrates():
    assert "celebrate()" in _read(
        "cloud/app/agent/tools/schemas/goal_tools.py"), (
        "a month-long goal ends in a text message and silence again")


def test_a_focus_session_changes_her():
    src = _read("cloud/app/agent/tools/schemas/life_tools/focus.py")
    assert "focus_begin()" in src, "the focus melody on the board stays unused"
    assert "focus_end()" in src


def test_small_things_get_a_small_reaction():
    """Ticking a task must not look like finishing a goal.

    A full celebration ten times a day is not encouragement, it is noise — and
    it devalues the real one. Streaks under a week get the quiet acknowledgement
    for the same reason.
    """
    tasks = _read("cloud/app/agent/tools/schemas/task_tools.py")
    habits = _read("cloud/app/agent/tools/schemas/life_tools/habits.py")
    assert "acknowledge()" in tasks
    assert "streak >= 7" in habits, (
        "every habit check-in now throws a party, which makes the party mean "
        "nothing")


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
