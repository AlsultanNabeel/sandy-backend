"""Held actions: a delete or bulk change waits for the user's yes, or for which one.

The pending dict's lifecycle and store are `brain/pending.py`; yes/no is read by
one normalized resolver, below, on chat and voice alike.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from app.brain import pending as P
from app.brain import tools
from app.brain.ctx import TurnCtx
from app.brain.matching import match_key
from app.utils.nlp_normalizer import normalize_user_message

PENDING_TYPE = "brain_confirm"

CANCELLED_REPLY = "تمام، ما عملت إشي."


def hold(steps: List[Dict[str, Any]]) -> Dict[str, Any]:
    """One pending for every held action of a turn: one question, one yes runs them all.
    Each step is {tool, args, summary}."""
    return P.create({"type": PENDING_TYPE, "action": "execute", "steps": steps,
                     "summary": " و".join(s["summary"] for s in steps)})


def with_step(held: Optional[Dict[str, Any]], name: str, args: Dict[str, Any],
              summary: str) -> Dict[str, Any]:
    """``held`` with one more action (the same call twice is held once)."""
    steps = list((held or {}).get("steps") or [])
    if not any(s["tool"] == name and s["args"] == args for s in steps):
        steps.append({"tool": name, "args": args, "summary": summary})
    return hold(steps)


def question(summary: str) -> str:
    return f"متأكد إنك بدك {summary}؟ (اه/لأ)"


def live(pending: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The pending if it is ours and not expired/consumed, else None."""
    if not isinstance(pending, dict) or pending.get("type") != PENDING_TYPE:
        return None
    return pending if P.live(pending) else None


def asked_again(held: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """An answer that is neither yes nor no: the question is asked once more, on chat and
    voice alike. A second unclear answer lets it go (None), so an old yes cannot fire later."""
    return None if held.get("asked_again") else {**held, "asked_again": True}


# ── reading the answer ───────────────────────────────────────────────────────
# The answer is the opening of the reply: yes/no words, the held action's own verb
# («احذفيها»), and filler («متأكد»، «يا ساندي»). What follows is a new request
# («اه وضيفي خبز»), handed to the model. A trigger word buried later in a story is
# never read as an answer.

_AFFIRM = {
    "اه", "نعم", "ايوه", "ايوا", "اكيد", "تمام", "تمم", "ماشي", "اوك", "اوكي", "حسنا",
    "صح", "طبعا", "yes", "ok", "okay", "sure", "yep", "yup", "confirmed",
}
# Only as the whole reply: «اي واحدة؟» is a question, not a yes.
_AFFIRM_ALONE = {"اي", "ايه", "y"}
_CANCEL = {"لا", "لاء", "الغاء", "مش", "بطل", "بلاش", "انسي", "انسيها", "انساها",
           "وقف", "وقفي", "no", "cancel", "nope", "dont", "stop", "nah", "n"}
# «خلص» alone is «drop it»; next to a yes or the action's verb («خلص احذفيها») it is «go on».
_SOFT_CANCEL = {"خلص", "خلاص"}
_NEGATORS = {"لا", "ما", "مش"}
_FILLER = {"متاكد", "متاكده", "ساندي", "يا", "يلا", "طيب", "طب", "بس", "لو", "سمحت",
           "please", "هلا", "هلق", "الان", "حبيبتي", "والله"}
# Whole phrases that are a yes («مش مشكلة احذفي»), read before the words.
_YES_PHRASES = ("مش مشكله", "ما في مشكله", "مافي مشكله", "لا مشكله", "ولا يهمك", "عادي")
# The held action's own verbs, by the verb its question opens with.
_VERBS = {"تحذف": ("احذف", "امسح", "شيل"), "تلغي": ("الغ",), "تعدل": ("عدل", "غير"),
          "تخلص": ("خلصي",)}
_ANY_VERB = ("نفذ", "اعمل", "كمل", "امش")


def _norm_answer(text: str) -> str:
    """Fold digits, punctuation, diacritics, emoji and Arabic letter variants, so
    «آه»، «اه.»، «اه 👍» and «اه صح» reduce to comparable tokens."""
    v = normalize_user_message(str(text or "")).lower()
    for a, b in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ٱ", "ا"),
                 ("ة", "ه"), ("ى", "ي"), ("ؤ", "و"), ("ئ", "ي")):
        v = v.replace(a, b)
    v = re.sub(r"[ً-ْ]", "", v)
    return " ".join(re.sub(r"[^\w\s]", " ", v).split())


def _verbs(held: Optional[Dict[str, Any]]) -> Tuple[str, ...]:
    """Roots that mean «do it» for this held action; a delete's when none is given."""
    summary = _norm_answer(str((held or {}).get("summary") or "تحذف"))
    first = summary.split()[0] if summary else ""
    return _VERBS.get(first, ()) + _ANY_VERB


def _is_verb(word: str, roots: Tuple[str, ...]) -> bool:
    """«احذفيها»، «امسحهم», and «تحذفها» as in «لا تحذفها»."""
    w = word[1:] if word.startswith("و") and len(word) > 3 else word
    return any(w.startswith(r) or w.startswith("ت" + r[1:]) for r in roots)


def read(text: str, held: Optional[Dict[str, Any]] = None) -> Tuple[str, bool]:
    """(yes | no | other, whether a new request follows the answer). Cancellation wins a
    mixed answer («اه بس لا»): it is the safe side of a destructive hold."""
    v = _norm_answer(text)
    if v in _AFFIRM_ALONE:
        return "yes", False
    for phrase in _YES_PHRASES:
        v = re.sub(rf"(^| ){phrase}(?= |$)", r"\1اه", v)
    words, roots = v.split(), _verbs(held)
    yes = no = soft = False
    end = len(words)
    for i, w in enumerate(words):
        if _is_verb(w, roots):
            negated = i > 0 and words[i - 1] in _NEGATORS
            no, yes = no or negated, yes or not negated
        elif w in _AFFIRM:
            yes = True
        elif w in _CANCEL or w.startswith("الغ"):
            no = True
        elif w in _SOFT_CANCEL:
            soft = True
        elif w not in _FILLER:
            end = i
            break
    rest = end < len(words)
    if no or (soft and not yes):
        return "no", rest
    if yes and rest and words[end - 1] == "بس":
        # «اه بس خليني أفكر»: a yes with a «but» after it is not a yes.
        return "other", rest
    return ("yes", rest) if yes else ("other", rest)


def answer(text: str, held: Optional[Dict[str, Any]] = None) -> str:
    """yes | no | other."""
    return read(text, held)[0]


def run_held(pending: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    """Runs every held action; ok only when all of them were. The yes covers these steps
    only: whatever the same message asks next («اه واحذفي كمان…») asks again."""
    ctx.confirmed = True
    try:
        results = [tools.execute(s["tool"], s.get("args") or {}, ctx)
                   for s in pending.get("steps") or []]
    finally:
        ctx.confirmed = False
    out: Dict[str, Any] = {"ok": bool(results) and all(r.get("ok") for r in results),
                           "reply": "\n".join(r["reply"] for r in results if r.get("reply"))}
    if any(r.get("broke") for r in results):
        out["broke"] = True
    return out


# ── "which one?" — two rows match and the user picks by number ──────────────

CHOOSE = "choose"
# Words with a leading «ال» and «و» already taken off.
_ORDINALS = {"اول": 0, "اولي": 0, "تاني": 1, "تانيه": 1, "ثاني": 1, "ثانيه": 1,
             "تالت": 2, "تالته": 2, "ثالث": 2, "ثالثه": 2, "رابع": 3, "رابعه": 3,
             "خامس": 4, "خامسه": 4, "اخير": -1, "اخيره": -1, "اخر": -1,
             # A bare number word is that one: «اتنين» is the second, not both.
             "واحد": 0, "وحده": 0, "اتنين": 1, "اثنين": 1, "تنتين": 1, "ثنتين": 1,
             "تلاته": 2, "ثلاثه": 2, "اربعه": 3, "خمسه": 4}
_ALL = {"كلهم", "كل", "كلهن", "كلها"}
# «الاتنين» / «التنتين» with the article is «both».
_BOTH = {"الاتنين", "الاثنين", "التنتين", "الثنتين"}
_ARABIC_NUMS = "١٢٣٤٥٦٧٨٩"


def hold_choice(name: str, args: Dict[str, Any],
                candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    return P.create({"type": PENDING_TYPE, "action": CHOOSE, "tool": name,
                     "args": args, "candidates": candidates})


def choice_question(candidates: List[Dict[str, Any]]) -> str:
    lines = []
    for n, c in enumerate(candidates):
        due = f" ({c['due'][:10]})" if c.get("due") else ""
        lines.append(f"{_ARABIC_NUMS[n] if n < 9 else n + 1}. {c['text']}{due}")
    return "لقيت أكتر من وحدة:\n" + "\n".join(lines) + "\nأي وحدة؟ (رقمها، أو «كلهم»)"


def _position(word: str) -> Optional[int]:
    """The index a word names («التالتة»، «و3»، «اتنين»), or None."""
    for w in (word, word[1:] if word.startswith("و") else word):
        if w.isdigit():
            return int(w) - 1
        bare = w[2:] if w.startswith("ال") and len(w) > 3 else w
        if bare in _ORDINALS:
            return _ORDINALS[bare]
    return None


def pick(text: str, candidates: List[Dict[str, Any]]) -> Optional[List[str]]:
    """The chosen ids: one or several («الأولى والتالتة»), all of them for «كلهم», or
    None when the text is not a choice."""
    ids = [c["id"] for c in candidates]
    words = _norm_answer(text).split()
    if not words:
        return None
    if any(w in _BOTH or w in _ALL or (w.startswith("و") and w[1:] in _ALL) for w in words):
        return ids
    chosen: List[str] = []
    for w in words:
        n = _position(w)
        if n is not None and -len(ids) <= n < len(ids) and ids[n] not in chosen:
            chosen.append(ids[n])
    if chosen:
        return chosen
    # They named it instead: unique text match among the candidates.
    key = match_key(text)
    named = [c["id"] for c in candidates if key and key in match_key(c.get("text", ""))]
    return named if len(named) == 1 else None
