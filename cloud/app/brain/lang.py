"""Arabic and English are equal: the language of a turn, and every sentence the server
says itself in both.

A message is English when it has more Latin letters than Arabic ones, else Arabic; one
with no letters at all («2», «👍») keeps the language the conversation was in. The turn's
language is a context variable (`using`), set by `loop.run_turn` and read by `say`, so a
tool, the confirmation and the honesty check answer in it without being passed it.

Every phrase has both languages and the same slots (`tests/test_brain_language.py`). What
the model reads (notes, instructions) stays in one language; what the user reads is here.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

AR, EN = "ar", "en"

_ARABIC = re.compile(r"[؀-ۿ]")
_LATIN = re.compile(r"[A-Za-z]")
_current: ContextVar[str] = ContextVar("sandy_lang", default=AR)


def of(text: str, fallback: Optional[str] = None) -> str:
    """The language a text is written in; ``fallback`` (else Arabic) when it has no letters."""
    latin, arabic = len(_LATIN.findall(text or "")), len(_ARABIC.findall(text or ""))
    if not latin and not arabic:
        return fallback or AR
    return EN if latin > arabic else AR


@contextmanager
def using(language: str) -> Iterator[str]:
    token = _current.set(EN if language == EN else AR)
    try:
        yield _current.get()
    finally:
        _current.reset(token)


def settle(language: str) -> None:
    """Inside `using`: the turn's language once more is known (the conversation's, for a
    message with no letters). `using` still puts back what was there before it."""
    _current.set(EN if language == EN else AR)


def current() -> str:
    return _current.get()


def say(key: str, **slots: object) -> str:
    """The phrase in the turn's language, its slots filled."""
    return PHRASES[key][_current.get()].format(**slots)


PHRASES = {
    "error": {"ar": "حصل خطأ، حاول مرة ثانية.",
              "en": "Something went wrong, please try again."},
    "gave_up": {"ar": "ما قدرت أكمّل هالطلب، جرّب تحكيه بطريقة تانية.",
                "en": "I couldn't finish that. Try saying it another way."},
    # A turn that broke after it wrote: it happened, so it is answered (and kept in the
    # send ledger as done), never run again by a resend.
    "after_writes": {"ar": "صار خطأ بنص الطلب بعد ما نفّذت جزء منه. شوف القوائم قبل ما تعيده.",
                     "en": "Something went wrong partway, after part of it was done. "
                           "Check your lists before asking again."},
    "done": {"ar": "تم ✅", "en": "Done ✅"},
}
