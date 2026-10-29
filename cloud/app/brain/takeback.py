"""A turn does not take back what it just did (eval, 29 Oct 2026, on the real model).

«no, I meant 60 not 50» corrected the expense and then deleted it in the same step; «turn off
the AC in an hour» set it for later and then turned it off now. The tool that would take it
back asks here first (`log_delete`, `list_delete`, `device_control`) and is refused. The
refusal is for the model to read, never the user: it carries no `reply`, so the honesty check
never shows it, and the model's own answer says what stands.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from app.brain.ctx import TurnCtx, refused
from app.brain.matching import match_key

logger = logging.getLogger(__name__)

# A delete of a row the same turn corrected takes the correction back with it.
_CORRECTED_BY = {"log_delete": "log_update", "list_delete": "list_update"}
# «now» said beside a time: the command is asked for now too, not for later only.
_NOW = {"now", "immediately", "هلق", "هسا", "هسه", "حين", "حالا", "فورا", "دغري"}


def _ids(args: Dict[str, Any]) -> set:
    return {str(i) for i in [args.get("id"), *(args.get("ids") or [])] if i}


def _asked_now(message: str) -> bool:
    key = match_key(message)
    return bool(_NOW & set(key.split())) or "right away" in key


def _no(name: str, why: str) -> Dict[str, Any]:
    logger.warning("[brain] tool %s refused: it takes back what this turn did", name)
    return refused(why)


def deleting(name: str, args: Dict[str, Any], ctx: TurnCtx) -> Optional[Dict[str, Any]]:
    """A refusal when this delete names a row the same turn corrected."""
    fixed = {i for n, a, ok in ctx.calls if ok and n == _CORRECTED_BY[name] for i in _ids(a)}
    if _ids(args) & fixed:
        return _no(name, "not deleted: this row was corrected earlier in this turn and the "
                         "correction stands; tell the user what it is now")
    return None


def switching(args: Dict[str, Any], ctx: TurnCtx) -> Optional[Dict[str, Any]]:
    """A refusal when this device command is the one the same turn set for later, and the
    message did not ask for it now as well («… now and again at 11pm»)."""
    if _asked_now(ctx.message):
        return None
    devices = {str(d) for d in [args.get("device"), *(args.get("devices") or [])] if d}
    command = str(args.get("value") or args.get("action") or "")
    for n, a, ok in ctx.calls:
        if ok and n == "schedule" and str(a.get("device") or "") in devices \
                and str(a.get("value") or a.get("action") or "") == command:
            return _no("device_control", "not sent now: this command is set for later in this "
                                         "turn; tell the user when it will run")
    return None
