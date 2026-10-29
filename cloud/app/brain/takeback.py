"""A turn does not take back what it just did (eval, 29 Oct 2026, on the real model).

«no, I meant 60 not 50» corrected the expense and then deleted it in the same step; «turn off
the AC in an hour» set it for later and then turned it off now. What a turn corrected and set
for later is kept as the tools resolved it (the row's id, the device's name and the command
it sends), never as the words the model passed: an update and a delete with no id both name
the newest row, «AC» and «ac» are one device. The tool that would take it back asks here
first (`log_delete`, `list_delete`, `device_control`) and is refused. The refusal is for the
model to read, never the user: it carries no `reply`, so the honesty check never shows it,
and the model's own answer says what stands.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List

from app.brain.ctx import TurnCtx, refused
from app.brain.matching import match_key

logger = logging.getLogger(__name__)

# «now» said beside a time: the command is asked for now too, not for later only.
_NOW = {"now", "immediately", "هلق", "هسا", "هسه", "حين", "حالا", "فورا", "دغري"}


def _asked_now(message: str) -> bool:
    key = match_key(message)
    return bool(_NOW & set(key.split())) or "right away" in key


def corrected(ctx: TurnCtx, rows: Iterable[Dict[str, Any]]) -> None:
    """The rows an update of this turn changed."""
    ctx.corrected.update(str(r["id"]) for r in rows)


def set_for_later(ctx: TurnCtx, device: str, command: str) -> None:
    """A device command this turn set for later: the device's name and what it will send."""
    ctx.for_later.add((device, command))


def not_corrected(name: str, picked: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    """``picked`` without the rows this turn corrected; a refusal when they were all of it."""
    if "rows" not in picked:
        return picked
    rows = [r for r in picked["rows"] if str(r["id"]) not in ctx.corrected]
    if picked["rows"] and not rows:
        logger.warning("[brain] tool %s refused: it deletes what this turn corrected", name)
        return refused("not deleted: this row was corrected earlier in this turn and the "
                       "correction stands; tell the user what it is now")
    return {**picked, "rows": rows}


def now_or_later(ctx: TurnCtx, devices: List[Dict[str, Any]], action: str, value: Any):
    """(devices to switch now, labels left for later): a device whose command this turn set
    for later is not switched now, unless the message asked for it now as well («… now and
    again at 11pm»)."""
    from app.features.device_store import command_payload

    if not ctx.for_later or _asked_now(ctx.message):
        return devices, []
    now, later = [], []
    for d in devices:
        res = command_payload(d, action, value)
        if res.get("ok") and (d["name"], res["payload"]) in ctx.for_later:
            later.append(d.get("label") or d["name"])
        else:
            now.append(d)
    if later:
        logger.warning("[brain] tool device_control: %d device(s) left for later", len(later))
    return now, later


def left_for_later() -> Dict[str, Any]:
    return refused("not sent now: this command is set for later in this turn; tell the user "
                   "when it will run")
