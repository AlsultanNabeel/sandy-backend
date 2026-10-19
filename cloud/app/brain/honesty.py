"""A reply never says she did what no tool did (C10, held by the server, not the prompt).

On 19 Oct 2026 she said «حذفت» to four deletes that had not happened: one waited for a
yes, one was an edit that changed nothing. The prompt already said «don't say you did it
before its result comes back»; a rule the model can break is not a guarantee. So the
words that claim a write (deleted, removed, added, changed, cancelled) are read here, and
each must be backed by a tool of its kind that worked in the same turn.

Chat replaces the sentence that claims it with what the tools really said; voice, whose
words are already heard, is told to put it right at once (`VOICE_CORRECTION`).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# The past-tense words that say a write happened, by its kind, as `_norm` leaves them.
_CLAIMS: Dict[str, Tuple[str, ...]] = {
    "delete": ("حذفت", "انحذف", "انحذفت", "انحذفو", "شلت", "انشال", "انشالت", "مسحت",
               "انمسح", "انمسحت"),
    "cancel": ("لغيت", "الغيت", "انلغي", "انلغت"),
    "edit": ("عدلت", "غيرت", "اتعدل", "اتعدلت"),
    "add": ("ضفت", "اضفت", "انضاف", "انضافت", "سجلت", "حطيت"),
}
# A pronoun ending: «حذفتها»، «شلتهم»، «ضفتلك».
_ENDINGS = ("", "ها", "هم", "هن", "ه", "و", "ك", "لك", "لها", "له", "لهم", "ي")
# What says it did not happen: «ما حذفت»، «لسا ما ضفته»، «مش رح».
_NOT = {"ما", "مش", "لسا", "لسه", "ولا", "بدون", "قبل", "لم", "لا", "مو", "رح", "راح", "بدي"}

# The tools that back each claim when they worked. An undo puts a row back or takes it
# away, so it backs any of them; on voice, `confirm` is the yes that ran a held bulk change.
BACKED_BY: Dict[str, Set[str]] = {
    "delete": {"list_delete", "log_delete", "undo", "confirm"},
    "cancel": {"schedule_cancel", "undo", "confirm"},
    "edit": {"list_update", "log_update", "schedule_update", "list_add", "undo", "confirm"},
    "add": {"list_add", "remember", "schedule", "undo"},
}

NOTHING_DONE = "لسا ما عملت هالإشي فعلياً. احكيلي مرة تانية شو بدك بالزبط وبعمله هلّق."

VOICE_CORRECTION = ("[تنبيه من النظام، مش من المستخدم: قلتي إنك {what} بس ما في أداة نفّذت هالإشي "
                    "بهالدور، يعني ما انعمل. صحّحي حالك هلّق بجملة قصيرة: قوليله إنه ما انعمل لسا، "
                    "واسأليه إذا بدّه تعمليه، أو نفّذيه بالأداة إذا طلبه.]")
_SAID = {"delete": "حذفتي", "cancel": "لغيتي", "edit": "عدّلتي", "add": "ضفتي"}


def _norm(text: str) -> List[str]:
    v = re.sub(r"[ً-ْـ]", "", str(text or ""))
    for a, b in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ى", "ي"), ("ة", "ه")):
        v = v.replace(a, b)
    return re.findall(r"[ء-ي]+", v)


def _kind_of(word: str) -> Optional[str]:
    for w in (word, word[1:] if word[:1] in ("و", "ف") and len(word) > 4 else word):
        for kind, stems in _CLAIMS.items():
            if any(w == s + e for s in stems for e in _ENDINGS):
                return kind
    return None


def claims(text: str) -> Set[str]:
    """The kinds of write the text says happened; a negated one («ما حذفت») is not a claim."""
    words = _norm(text)
    found = set()
    for i, w in enumerate(words):
        kind = _kind_of(w)
        if kind and not ({words[j] for j in range(max(0, i - 2), i)} & _NOT
                         or any(words[j].startswith(("فما", "وما")) for j in range(max(0, i - 2), i))):
            found.add(kind)
    return found


def unbacked(text: str, worked: Iterable[str]) -> Set[str]:
    """The claims in ``text`` that no tool in ``worked`` (the names of the tools of the turn
    that worked) backs."""
    done = set(worked)
    return {k for k in claims(text) if not BACKED_BY[k] & done}


def _sentences(text: str) -> List[str]:
    return [s for s in re.split(r"(?<=[.!؟?\n])", text) if s.strip()]


def honest(text: str, worked: Iterable[str], results: List[Tuple[str, Dict[str, Any]]],
           question: str = "") -> str:
    """``text`` with every sentence that claims an unbacked write taken out and what the
    tools really said in its place; NOTHING_DONE when nothing is left to say. ``question``
    is the held action's question, ours and already true, kept last."""
    worked = list(worked)
    body = text[: -len(question)] if question and text.endswith(question) else text
    kept = "".join(s for s in _sentences(body) if not unbacked(s, worked)).strip()
    said = [str(r["reply"]).strip() for _, r in results
            if r.get("reply") and not r.get("needs_confirmation")]
    out = "\n".join(t for t in [*dict.fromkeys(said), kept] if t)
    if not out and not question:
        out = NOTHING_DONE
    return "\n".join(t for t in (out, question) if t)


def correct(text: str, worked: Iterable[str], results: List[Tuple[str, Dict[str, Any]]],
            question: str = "") -> str:
    """The reply to send: ``text`` itself when everything it claims is backed."""
    missing = unbacked(text, worked)
    if not missing:
        return text
    logger.warning("[honesty] reply claimed %s with no tool behind it; replaced", sorted(missing))
    return honest(text, worked, results, question)


def voice_correction(text: str, worked: Iterable[str]) -> Optional[str]:
    """What she is told when what she just said claims a write no tool of the turn did."""
    missing = unbacked(text, worked)
    if not missing:
        return None
    logger.warning("[honesty] voice reply claimed %s with no tool behind it", sorted(missing))
    return VOICE_CORRECTION.format(what=" و".join(_SAID[k] for k in sorted(missing)))
