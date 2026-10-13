"""Turns that are not someone talking to her: far away, the TV, or a recogniser's invention.

Two checks, in any language (she must understand whatever language he speaks):

- **Level.** A turn whose voice is much quieter than his own speaking level in this call
  (`NearLevel`, learned from his turns) is distant talk or the TV, and never opens a turn.
- **Inventions.** A recogniser hearing noise writes a few stock phrases («¿Qué?»,
  «Gracias», «شكرا على المشاهدة»). Such a turn is dropped only when the phrase is the whole
  turn and the turn was quiet or very short (`suspect`); said clearly and close, it goes
  through.

Gemini Live gives no "no speech" probability or confidence for its transcript (its
`Transcription` carries text, `finished` and a language code only), so neither is used.
"""
from __future__ import annotations

import re
import statistics
from typing import Dict, Iterable, List, Optional

# A voice under this share of his own level is not him talking to her (about -8 dB).
NEAR_FACTOR = 0.4
# Under this share, or shorter than this, a turn is quiet or short enough to be an invention.
SUSPECT_FACTOR = 0.6
SUSPECT_SPEECH_MS = 400.0
# His level is the median of his last few turns, so one shout does not move it.
NEAR_TURNS = 5
# A held reply is let go after this long with no transcript at all.
HOLD_MAX_S = 1.5

# What recognisers write for noise, normalised (`_norm`). Whole-turn matches only.
_INVENTIONS = (
    "que", "qué", "gracias", "thank you", "thanks for watching", "thank you for watching",
    "شكرا", "شكرا لكم", "شكرا على المشاهدة",
    "شكرا للمشاهدة", "اشتركوا في القناة", "ترجمة نانسي قنقر", "موسيقى",
)
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_TASHKEEL = re.compile(r"[ً-ْـ]")


def _norm(text: str) -> str:
    t = _TASHKEEL.sub("", (text or "").lower())
    t = _PUNCT.sub(" ", t).replace("ـ", "")
    t = t.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ى", "ي")
    return " ".join(t.split())


_NORMED = frozenset(_norm(p) for p in _INVENTIONS)


def is_invention(text: str) -> bool:
    """The whole turn is one of the stock phrases."""
    t = _norm(text)
    return bool(t) and t in _NORMED


def could_be_invention(text: str) -> bool:
    """So far the turn is still the start of a stock phrase (its reply waits to know)."""
    t = _norm(text)
    return not t or any(p == t or p.startswith(t + " ") for p in _NORMED)


def level(rms_values: Iterable[float]) -> Optional[float]:
    values: List[float] = [float(v) for v in rms_values]
    return statistics.median(values) if values else None


def near_level(state: Dict) -> Optional[float]:
    """His own speaking level in this call, None until a turn of his has set it."""
    return level(state.get("near_levels") or ())


def learn(state: Dict, turn_level: Optional[float]) -> None:
    if turn_level:
        state["near_levels"] = (list(state.get("near_levels") or []) + [turn_level])[-NEAR_TURNS:]


def far(state: Dict, voice_level: Optional[float]) -> bool:
    """Much quieter than him: not a turn."""
    near = near_level(state)
    return bool(near and voice_level is not None and voice_level < near * NEAR_FACTOR)


def suspect(state: Dict, turn_level: Optional[float], speech_ms: float) -> bool:
    """Quiet or very short: if its transcript is a stock phrase, it is an invention."""
    near = near_level(state)
    quiet = bool(near and turn_level is not None and turn_level < near * SUSPECT_FACTOR)
    return quiet or speech_ms < SUSPECT_SPEECH_MS
