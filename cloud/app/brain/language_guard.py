"""A reply is in its message's language (held by the server, not only the prompt).

The prompt says so, and the model mostly listens; but with a long Arabic prompt it writes
Arabic to an English message now and then (and the other way round). So the reply is read
here: an English turn's reply may hold no Arabic word outside a «quoted» name, an Arabic
turn's may not be mostly English. One that breaks it is rewritten once by the model in the
right language; if that fails, the reply goes out as it was.
"""

from __future__ import annotations

import logging
import re
from typing import Callable

from app.brain import lang

logger = logging.getLogger(__name__)

_QUOTED = re.compile(r"«[^»]*»")
_ARABIC = re.compile(r"[؀-ۿ]")
_LATIN = re.compile(r"[A-Za-z]")

_REWRITE = {
    lang.EN: ("Rewrite this reply in natural English only. Keep «quoted» names, numbers and "
              "emoji as they are; add nothing, drop nothing. Answer with the reply alone."),
    lang.AR: ("أعيدي كتابة هالرد بالعربي بلهجتك بس. خلّي الأسماء اللي بين «» والأرقام والإيموجي "
              "زي ما هي؛ ما تزيدي ولا تشيلي إشي. جاوبي بالرد لحاله."),
}


def wrong_language(text: str, language: str) -> bool:
    plain = _QUOTED.sub("", text or "")
    arabic, latin = len(_ARABIC.findall(plain)), len(_LATIN.findall(plain))
    if language == lang.EN:
        return arabic > 0
    return latin > arabic


def ensure(text: str, complete: Callable) -> str:
    """``text`` in the turn's language: itself when it already is, else the model's
    rewrite of it, else (no answer, or still wrong) itself."""
    language = lang.current()
    if not text or not wrong_language(text, language):
        return text
    # `model.complete` answers None when the provider failed; it does not raise.
    reply = complete([{"role": "system", "content": _REWRITE[language]},
                      {"role": "user", "content": text}], [])
    out = (getattr(reply, "text", "") or "").strip()
    if not out or wrong_language(out, language):
        logger.warning("[language] rewrite still not in %s; reply kept", language)
        return text
    logger.info("[language] reply rewritten in %s", language)
    return out
