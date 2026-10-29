"""A reply never says she did what no tool did (C10, held by the server, not the prompt).

On 19 Oct 2026 she said «حذفت» to four deletes that had not happened: one waited for a
yes, one was an edit that changed nothing. The prompt already said «don't say you did it
before its result comes back»; a rule the model can break is not a guarantee. So the
words that claim a write (deleted, removed, added, changed, cancelled, done; «حذفت»،
«ضفت»، «تم»…) are read here, in Arabic and English alike, and each must be backed by a
tool of its kind that worked in the same turn. «Done» names no kind: any tool that worked
backs it.

Chat replaces the sentence that claims it with what the tools really said; voice, whose
words are already heard, is told to put it right at once (`voice_correction`, in
the language the turn was spoken in).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from app.brain import lang

logger = logging.getLogger(__name__)

# The past-tense words that say a write happened, by its kind, as `_norm` leaves them.
_CLAIMS: Dict[str, Tuple[str, ...]] = {
    "delete": ("حذفت", "انحذف", "انحذفت", "انحذفو", "شلت", "انشال", "انشالت", "مسحت",
               "انمسح", "انمسحت"),
    "cancel": ("لغيت", "الغيت", "انلغي", "انلغت"),
    "edit": ("عدلت", "غيرت", "اتعدل", "اتعدلت"),
    "add": ("ضفت", "اضفت", "انضاف", "انضافت", "سجلت", "حطيت"),
    "done": ("تم",),
}
# The same claims in English, whole words.
_CLAIMS_EN: Dict[str, Tuple[str, ...]] = {
    "delete": ("deleted", "removed", "erased", "cleared"),
    "cancel": ("cancelled", "canceled"),
    "edit": ("changed", "updated", "edited", "renamed", "moved", "rescheduled"),
    "add": ("added", "saved", "created", "scheduled", "logged"),
    "done": ("done",),
}
# What says it did not happen, or not yet, when it is the verb's own: «I haven't deleted»,
# «it will be added», «nothing was removed». Read back from the verb through `_VERB_EN` only,
# so «don't worry, I've deleted it» is a claim: «don't» is worry's.
_NOT_EN = {"not", "never", "no", "nothing", "none", "haven't", "hasn't", "hadn't", "didn't",
           "wasn't", "weren't", "won't", "can't", "cannot", "couldn't", "isn't", "aren't",
           "don't", "doesn't", "wouldn't", "shouldn't", "havent", "hasnt", "didnt", "wasnt",
           "isnt", "dont", "wont", "cant", "be", "will", "would", "to", "can", "could",
           "should", "shall", "may", "might", "must", "want", "wanna", "gonna", "if",
           "i'll", "it'll", "we'll", "you'll", "they'll"}
# What stands between a verb and its negation: «hasn't been deleted», «not yet added».
_VERB_EN = {"i", "you", "it", "we", "they", "he", "she", "them", "all", "both", "also", "just",
            "already", "actually", "really", "now", "yet", "fully", "successfully", "ever",
            "been", "being", "have", "has", "had", "is", "are", "was", "were", "am", "get",
            "got", "i've", "we've", "you've", "they've", "it's", "that's", "i'd", "i'm",
            "and", "or", "nor"}
# A pronoun ending: «حذفتها»، «شلتهم»، «ضفتلك».
_ENDINGS = ("", "ها", "هم", "هن", "ه", "و", "ك", "لك", "لها", "له", "لهم", "ي")
# What says it did not happen, when it is the verb's own: «ما حذفت»، «لسا ما ضفته»، «ولا
# شلته». «لا تقلق، حذفته» is a claim: «لا» is the reassurance's, not the verb's.
_NOT = {"ما", "مش", "ولا", "لم", "مو", "فما", "وما"}
# What stands between a verb and its negation: «ما كنت حذفته»، «ما فعلياً ضفته».
_VERB = {"كنت", "كان", "كانت", "بعد", "فعليا", "اصلا", "هلق", "لسا", "لسه"}

# The tools that back each claim when they worked. An undo puts a row back or takes it
# away, so it backs any of them; on voice, `confirm` is the yes that ran a held bulk change.
BACKED_BY: Dict[str, Set[str]] = {
    "delete": {"list_delete", "log_delete", "undo", "confirm"},
    "cancel": {"schedule_cancel", "undo", "confirm"},
    "edit": {"list_update", "log_update", "schedule_update", "list_add", "undo", "confirm"},
    "add": {"list_add", "remember", "schedule", "undo"},
}
_ANY = "done"


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


def _english(text: str) -> List[str]:
    return re.findall(r"[a-z']+", str(text or "").lower().replace("’", "'"))


def _clauses(text: str) -> List[str]:
    """A negation reaches no further than its clause: «لا تقلق، حذفته», «No, deleted»."""
    return re.split(r"[،,.!?؟;؛:\n—–]+", str(text or ""))


def _negated(words: List[str], i: int, nots: Set[str], between: Set[str]) -> bool:
    """Whether the verb at ``i`` is negated: read back through ``between`` to its negation."""
    j = i - 1
    while j >= 0 and words[j] in between:
        j -= 1
    return j >= 0 and words[j] in nots


def claims(text: str) -> Set[str]:
    """The kinds of write the text says happened; a negated one («ما حذفت», «I haven't
    deleted») or one still to come («it will be added») is not a claim. The negation is the
    verb's own: a reassurance before it («لا تقلق، حذفته», «no worries, deleted it») is not."""
    found = set()
    for clause in _clauses(text):
        words = _norm(clause)
        for i, w in enumerate(words):
            kind = _kind_of(w)
            if kind and not _negated(words, i, _NOT, _VERB):
                found.add(kind)
        english = _english(clause)
        for i, w in enumerate(english):
            kind = next((k for k, forms in _CLAIMS_EN.items() if w in forms), None)
            if kind and not _negated(english, i, _NOT_EN, _VERB_EN):
                found.add(kind)
    return found


def unbacked(text: str, worked: Iterable[str]) -> Set[str]:
    """The claims in ``text`` that no tool in ``worked`` (the names of the tools of the turn
    that worked) backs; «done» is backed by any of them."""
    done = set(worked)
    return {k for k in claims(text) if not (done if k == _ANY else BACKED_BY[k] & done)}


def _sentences(text: str) -> List[str]:
    return [s for s in re.split(r"(?<=[.!؟?\n])", text) if s.strip()]


def honest(text: str, worked: Iterable[str], results: List[Tuple[str, Dict[str, Any]]],
           question: str = "") -> str:
    """``text`` with every sentence that claims an unbacked write taken out and what the
    tools really said in its place; NOTHING_DONE when nothing is left to say. ``question``
    is the held action's question, ours and already true, kept last. A tool's reply the
    kept text already holds is not put in again: a reply rewritten after a first correction
    carries them already (`loop`, the second pass after the language check)."""
    worked = list(worked)
    body = text[: -len(question)] if question and text.endswith(question) else text
    kept = "".join(s for s in _sentences(body) if not unbacked(s, worked)).strip()
    said = [str(r["reply"]).strip() for _, r in results
            if r.get("reply") and not r.get("needs_confirmation")]
    out = "\n".join(t for t in [*(t for t in dict.fromkeys(said) if t not in kept), kept] if t)
    if not out and not question:
        out = lang.say("nothing_done")
    return "\n".join(t for t in (out, question) if t)


def correct(text: str, worked: Iterable[str], results: List[Tuple[str, Dict[str, Any]]],
            question: str = "") -> str:
    """The reply to send: ``text`` itself when everything it claims is backed."""
    missing = unbacked(text, worked)
    if not missing:
        return text
    logger.warning("[honesty] reply claimed %s with no tool behind it; replaced", sorted(missing))
    return honest(text, worked, results, question)


def voice_correction(text: str, worked: Iterable[str],
                     language: Optional[str] = None) -> Optional[str]:
    """What she is told when what she just said claims a write no tool of the turn did, in
    ``language`` (the turn's spoken one; else the current)."""
    missing = unbacked(text, worked)
    if not missing:
        return None
    logger.warning("[honesty] voice reply claimed %s with no tool behind it", sorted(missing))
    with lang.using(language or lang.current()):
        said = [lang.say(f"said_{k}") for k in sorted(missing)]
        what = said[0] if len(said) == 1 else lang.say(
            "names_last", names=lang.say("sep").join(said[:-1]), last=said[-1])
        return lang.say("voice_correction", what=what)
