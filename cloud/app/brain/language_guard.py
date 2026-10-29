"""A reply is in its message's language (held by the server, not only the prompt).

The prompt says so, and the model mostly listens; but with a long Arabic prompt it writes
Arabic to an English message now and then (and the other way round). So the reply is read
here: an English turn's reply may hold no Arabic word, an Arabic turn's may not be mostly
English words; names (quoted, the message's own, the tools'), links and numbers aside. One that breaks it is rewritten once by the model in the
right language; if that fails, the reply goes out as it was.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, Iterable, List, Tuple

from app.brain import lang

logger = logging.getLogger(__name__)

_QUOTED = re.compile(r"«[^»]*»")
_LINK = re.compile(r"https?://\S+|www\.\S+|\S+@\S+\.\S+")
# Letters only: Arabic punctuation («،», «؟») and digits («٥٠») name no language.
_ARABIC = re.compile(r"[ء-يٱ-ۓ]")
_ARABIC_WORD = re.compile(r"[ء-يٱ-ۓ]+")
_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")
_ARABIC_RUN = re.compile(r"[ء-يٱ-ۓ]+(?:\s+[ء-يٱ-ۓ]+)*")
_LATIN_RUN = re.compile(r"[A-Za-z][A-Za-z0-9'’-]*(?:\s+[A-Za-z0-9][A-Za-z0-9'’-]*)*")

# Handed over as text to translate: asked to «rewrite this reply», the model answered the
# Arabic in Arabic every time (29 Oct 2026).
_REWRITE = {
    lang.EN: ("You translate. Translate the reply below into natural, casual English. Keep «quoted» "
              "names, numbers and emoji as they are; add nothing, drop nothing. Answer with the "
              "English text alone."),
    lang.AR: ("إنتِ بتترجمي. ترجمي الرد اللي تحت للعربي بلهجة شامية عفوية. خلّي الأسماء اللي بين «» "
              "والأرقام والإيموجي زي ما هي؛ ما تزيدي ولا تشيلي إشي. جاوبي بالترجمة لحالها."),
}
_HEAD = {lang.EN: "The reply to translate:", lang.AR: "الرد اللي بدّه ترجمة:"}


def names_of(message: str, results: Iterable[Tuple[str, Dict[str, Any]]]) -> List[str]:
    """What a right reply may still hold in the other script: the words of the message in it
    («turn on ضو الصالة»), the tools' own replies (ours, already in the turn's language) and
    every word their calls were given (a device's or a row's name)."""
    found = [*_ARABIC_RUN.findall(message or ""), *_LATIN_RUN.findall(message or "")]
    for _, result in results or []:
        found += [str(v) for k, v in (result or {}).items()
                  if isinstance(v, str) and k in ("reply", "label", "name", "text")]
    return [n for n in dict.fromkeys(n.strip() for n in found) if n]


def _without_names(text: str, names: Iterable[str]) -> str:
    plain = _LINK.sub(" ", _QUOTED.sub(" ", text or ""))
    for name in sorted(names or (), key=len, reverse=True):
        plain = plain.replace(name, " ")
    return plain


def wrong_language(text: str, language: str, names: Iterable[str] = ()) -> bool:
    """Whether ``text`` is not in ``language``, its names, links and numbers aside. An English
    reply may hold no Arabic word; an Arabic one may not be mostly English words (a
    Capitalised one is a name: «iPhone Pro Max»)."""
    plain = _without_names(text, names)
    if language == lang.EN:
        return bool(_ARABIC.search(plain))
    latin = [w for w in _LATIN_WORD.findall(plain) if not w[0].isupper()]
    return len(latin) > 2 * len(_ARABIC_WORD.findall(plain))


def ensure(text: str, complete: Callable, names: Iterable[str] = ()) -> str:
    """``text`` in the turn's language: itself when it already is (``names`` aside, see
    `names_of`), else the model's rewrite of it, else (no answer, or still wrong) itself."""
    language = lang.current()
    if not text or not wrong_language(text, language, names):
        return text
    # `model.complete` answers None when the provider failed; it does not raise.
    reply = complete([{"role": "system", "content": _REWRITE[language]},
                      {"role": "user", "content": f"{_HEAD[language]}\n\n{text}"}], [])
    out = (getattr(reply, "text", "") or "").strip()
    if not out or wrong_language(out, language, names):
        logger.warning("[language] rewrite still not in %s; reply kept", language)
        return text
    logger.info("[language] reply rewritten in %s", language)
    return out
