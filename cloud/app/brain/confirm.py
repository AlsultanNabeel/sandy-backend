"""Held actions: a delete or bulk change waits for the user's yes.

The pending dict goes through the existing lifecycle (`agent/pending.py`) and
store (`agent/pending_store.py`); yes/no is read by the one normalized resolver
the old router and pending dispatch share (`executor/helpers.py`).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.agent.executor.helpers import _is_quick_confirmation, is_cancellation
from app.agent.pending import create_pending_action, get_valid_pending_action
from app.brain import tools
from app.brain.ctx import TurnCtx

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
