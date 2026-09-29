"""Held actions: a delete or bulk change waits for the user's yes.

The pending dict goes through the existing lifecycle (`agent/pending.py`) and
store (`agent/pending_store.py`); yes/no is read by the one normalized resolver
the old router and pending dispatch share (`executor/helpers.py`).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.agent.executor.helpers import _is_quick_confirmation, is_cancellation
from app.agent.pending import create_pending_action, get_valid_pending_action
from app.brain import tools
from app.brain.ctx import TurnCtx
from app.features.tasks_matcher import _task_match_key

PENDING_TYPE = "brain_confirm"

CANCELLED_REPLY = "تمام، ما عملت إشي."


def hold(name: str, args: Dict[str, Any], summary: str) -> Dict[str, Any]:
    return create_pending_action({"type": PENDING_TYPE, "action": "execute",
                                  "tool": name, "args": args, "summary": summary})


def question(summary: str) -> str:
    return f"متأكد إنك بدك {summary}؟ (اه/لأ)"


def live(pending: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The pending if it is ours and not expired/consumed, else None."""
    if not isinstance(pending, dict) or pending.get("type") != PENDING_TYPE:
        return None
    return get_valid_pending_action({"pending_action": dict(pending)})


def answer(text: str) -> str:
    """yes | no | other — cancellation is checked first, as the old flow does."""
    if is_cancellation(text):
        return "no"
    if _is_quick_confirmation(text):
        return "yes"
    return "other"


def run_held(pending: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    ctx.confirmed = True
    return tools.execute(pending["tool"], pending.get("args") or {}, ctx)


# ── "which one?" — two rows match and the user picks by number ──────────────

CHOOSE = "choose"
# Keys are already normalized by _task_match_key, which drops a leading «ال».
_ORDINALS = {"اول": 0, "اولي": 0, "تاني": 1, "تانيه": 1, "ثاني": 1, "ثانيه": 1,
             "تالت": 2, "تالته": 2, "ثالث": 2, "ثالثه": 2, "رابع": 3, "رابعه": 3,
             "خامس": 4, "خامسه": 4, "اخير": -1, "اخيره": -1, "اخر": -1}
_ALL = {"كلهم", "كل", "كلهن", "تنتين", "اتنين", "اثنين", "ثنتين"}
_ARABIC_NUMS = "١٢٣٤٥٦٧٨٩"


def hold_choice(name: str, args: Dict[str, Any],
                candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    return create_pending_action({"type": PENDING_TYPE, "action": CHOOSE, "tool": name,
                                  "args": args, "candidates": candidates})


def choice_question(candidates: List[Dict[str, Any]]) -> str:
    lines = []
    for n, c in enumerate(candidates):
        due = f" ({c['due'][:10]})" if c.get("due") else ""
        lines.append(f"{_ARABIC_NUMS[n] if n < 9 else n + 1}. {c['text']}{due}")
    return "لقيت أكتر من وحدة:\n" + "\n".join(lines) + "\nأي وحدة؟ (رقمها، أو «كلهم»)"


def pick(text: str, candidates: List[Dict[str, Any]]) -> Optional[List[str]]:
    """The chosen ids, all of them for «كلهم», or None when the text is not a choice."""
    key = _task_match_key(text)
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
    named = [c["id"] for c in candidates if key in _task_match_key(c.get("text", ""))]
    return named if len(named) == 1 else None
