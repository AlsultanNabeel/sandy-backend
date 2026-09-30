"""Held actions: a delete or bulk change waits for the user's yes, or for which one.

The pending dict's lifecycle and store are `brain/pending.py`; yes/no is read by
one normalized resolver, below, on chat and voice alike.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.brain import pending as P
from app.brain import tools
from app.brain.ctx import TurnCtx
from app.brain.matching import match_key
from app.utils.nlp_normalizer import normalize_user_message

PENDING_TYPE = "brain_confirm"

CANCELLED_REPLY = "تمام، ما عملت إشي."


def hold(name: str, args: Dict[str, Any], summary: str) -> Dict[str, Any]:
    return P.create({"type": PENDING_TYPE, "action": "execute",
                     "tool": name, "args": args, "summary": summary})


def question(summary: str) -> str:
    return f"متأكد إنك بدك {summary}؟ (اه/لأ)"


def live(pending: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The pending if it is ours and not expired/consumed, else None."""
    if not isinstance(pending, dict) or pending.get("type") != PENDING_TYPE:
        return None
    return pending if P.live(pending) else None


# A bare word to confirm; a short phrase only when it opens with an unambiguous yes
# («اه صح»). «اي»/«ايه» are not leads: they only confirm alone.
_AFFIRM_EXACT = {
    "اه", "ايه", "اي", "نعم", "ايوه", "ايوا", "اكيد", "تمام", "تمم", "ماشي",
    "اوك", "اوكي", "حسنا", "صح", "احذف", "احذفها", "احذفهم", "نفذ", "اعمل",
    "yes", "ok", "okay", "sure", "yep", "yup", "confirmed", "y",
}
_AFFIRM_LEAD = {
    "اه", "نعم", "ايوه", "ايوا", "اكيد", "تمام", "ماشي", "اوك", "اوكي",
    "yes", "ok", "okay", "sure", "confirmed",
}
_CANCEL_EXACT = {
    "لا", "لاء", "الغ", "الغاء", "مش", "خلص", "بطل", "بلاش",
    "no", "cancel", "nope", "dont", "stop", "nah", "n",
}
_CANCEL_SUB = (
    "لا تحذف", "مش الان", "انسي", "وقف", "وقفي",
    "الغي", "الغيها", "الغيهم", "لا تضيف",
)
# Replies longer than this are a new message, not an answer: a trigger word
# buried in a story must not confirm or cancel anything.
_MAX_ANSWER_WORDS = 4


def _norm_answer(text: str) -> str:
    """Fold digits, punctuation, tatweel, emoji and Arabic letter variants, so
    «آه»، «اه.»، «اه 👍» and «اه صح» reduce to comparable tokens."""
    v = normalize_user_message(str(text or "")).lower()
    for a, b in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ٱ", "ا"),
                 ("ة", "ه"), ("ى", "ي"), ("ؤ", "و"), ("ئ", "ي")):
        v = v.replace(a, b)
    return " ".join(re.sub(r"[^\w\s]", " ", v).split())


def answer(text: str) -> str:
    """yes | no | other. Cancellation wins a mixed reply («اه بس لا»): it is the
    safe side of a destructive hold."""
    v = _norm_answer(text)
    words = v.split()
    if not v or len(words) > _MAX_ANSWER_WORDS:
        return "other"
    if any(w in _CANCEL_EXACT for w in words) or any(s in v for s in _CANCEL_SUB):
        return "no"
    if v in _AFFIRM_EXACT or (len(words) >= 2 and words[0] in _AFFIRM_LEAD):
        return "yes"
    return "other"


def run_held(pending: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    ctx.confirmed = True
    return tools.execute(pending["tool"], pending.get("args") or {}, ctx)


# ── "which one?" — two rows match and the user picks by number ──────────────

CHOOSE = "choose"
# Keys are already normalized by match_key, which drops a leading «ال».
_ORDINALS = {"اول": 0, "اولي": 0, "تاني": 1, "تانيه": 1, "ثاني": 1, "ثانيه": 1,
             "تالت": 2, "تالته": 2, "ثالث": 2, "ثالثه": 2, "رابع": 3, "رابعه": 3,
             "خامس": 4, "خامسه": 4, "اخير": -1, "اخيره": -1, "اخر": -1}
_ALL = {"كلهم", "كل", "كلهن", "تنتين", "اتنين", "اثنين", "ثنتين"}
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


def pick(text: str, candidates: List[Dict[str, Any]]) -> Optional[List[str]]:
    """The chosen ids, all of them for «كلهم», or None when the text is not a choice."""
    key = match_key(text)
    ids = [c["id"] for c in candidates]
    if not key:
        return None
    if key in _ALL or any(w in _ALL for w in key.split()):
        return ids
    digits = re.findall(r"\d+", key)
    if digits and 1 <= int(digits[0]) <= len(ids):
        return [ids[int(digits[0]) - 1]]
    for word in (key, *key.split()):
        if word in _ORDINALS:
            n = _ORDINALS[word]
            if n < len(ids):
                return [ids[n]]
    # They named it instead: unique text match among the candidates.
    named = [c["id"] for c in candidates if key in match_key(c.get("text", ""))]
    return named if len(named) == 1 else None
