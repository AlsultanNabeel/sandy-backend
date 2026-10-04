"""Her face on the robot follows what she is saying; the names are the firmware's."""
from __future__ import annotations

import re
from pathlib import Path

from app.api.voice_ws import face

_FIRMWARE = Path(__file__).resolve().parents[1] / "firmware/brain-core/main/sandy_mqtt.c"


def test_what_she_says_picks_the_face():
    assert face.mood_of("للأسف ما لقيت الموعد") == "sad"
    assert face.mood_of("ألف مبروك على الشغل الجديد!") == "big_happy"
    assert face.mood_of("واو، عن جد؟") == "surprised"
    assert face.mood_of("هههه ماشي") == "playful"
    assert face.mood_of("Congratulations on the new job") == "big_happy"


def test_a_plain_reply_has_no_mood_of_its_own():
    assert face.mood_of("ضفت الحليب لقائمة التسوق") == ""
    assert face.mood_of("") == ""


def test_the_sharper_mood_wins_a_mixed_reply():
    assert face.mood_of("للأسف ما زبط، بس يلا منجرب كمان مرة") == "sad"


def test_every_mood_is_one_the_robot_knows():
    known = set(re.findall(r'\{"(\w+)",\s*MOOD_', _FIRMWARE.read_text()))
    assert {name for name, _ in face._MOODS} | {face.AFTER_DEFAULT} <= known
