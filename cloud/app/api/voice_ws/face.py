"""Her face while she talks on the robot: the mood of what she is saying, read from
her own transcript as it streams in. Words only, no model call, so the face keeps up
with the voice. The names are the firmware's (`MOOD_MAP` in sandy_face.c)."""
from __future__ import annotations

import re

# After a reply with no clear mood her face still answers: a warm one.
AFTER_DEFAULT = "happy"

_DIACRITICS = re.compile(r"[ً-ْـ]")

# First match wins, so the sharper moods come before the broad ones.
_MOODS = (
    ("sad", r"للأسف|للاسف|آسفة|اسفة|بعتذر|معلش|زعلت|حزين|الله يرحم|بتمنالك الشفاء|sorry|sad"),
    ("worried", r"انتبه|دير بالك|ديري بالك|خطر|قلقانة|خايفة|be careful|worried"),
    ("love", r"بحبك|حبيبي|حبيبتي|يا قلبي|يا عمري|love you"),
    ("big_happy", r"مبروك|ألف مبروك|الف مبروك|يا سلام|رائع|خطير|congrat|amazing"),
    ("proud", r"أحسنت|احسنت|برافو|شاطر|فخورة|كفو|well done|proud"),
    ("surprised", r"واو|معقول|عن جد|عنجد|يا الله|ما توقعت|wow|really\?"),
    ("playful", r"ههه|هاها|بمزح|lol|haha"),
    ("grateful", r"شكرا|شكراً|يسلمو|تسلم|thank"),
    ("confused", r"ما فهمت|مش فاهمة|شو قصدك|ممكن تعيد|didn't catch|not sure what"),
    ("thinking", r"خليني أشوف|خليني اشوف|لحظة|بفكر|let me check|one moment"),
    ("excited", r"يلا|يلّا|متحمسة|let's go|excited"),
)
_COMPILED = tuple((name, re.compile(pattern, re.IGNORECASE)) for name, pattern in _MOODS)


def _plain(text: str) -> str:
    text = _DIACRITICS.sub("", text or "")
    return re.sub("[إأآ]", "ا", text)


def mood_of(text: str) -> str:
    """The firmware mood name for what she is saying, or "" when nothing stands out."""
    plain = _plain(text)
    for name, pattern in _COMPILED:
        if pattern.search(plain) or pattern.search(text or ""):
            return name
    return ""
