"""A summary as text for the app: the `summarize` tool's rows, one model call, no tools."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, Optional

from app.agent.context_builder import build_effective_persona
from app.brain import model, tools_blocks
from app.brain.ctx import TurnCtx
from app.utils.user_profiles import address_instruction

logger = logging.getLogger(__name__)

EMPTY_REPLY = "ما في إشي مسجّل بهالفترة."


def summarize_text(user_id: str, period: str, focus: str = "", *,
                   complete: Optional[Callable] = None) -> Dict[str, Any]:
    """{"ok", "text", "count"}; ``ok`` False with ``error`` when the period is bad or the model failed."""
    result = tools_blocks.summarize({"period": period, "focus": focus},
                                    TurnCtx(user_id=user_id, source="app"))
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "bad_period")}
    if not result["rows"]:
        return {"ok": True, "text": EMPTY_REPLY, "count": 0}
    system = "\n\n".join(p for p in (build_effective_persona(user_id or None),
                                     address_instruction(), result["instruction"]) if p)
    rows = json.dumps({k: result[k] for k in ("period", "from", "to", "rows")},
                      ensure_ascii=False, default=str)
    reply = (complete or model.complete)(
        [{"role": "system", "content": system}, {"role": "user", "content": rows}], [])
    if reply is None or not reply.text:
        logger.warning("[brain] summary: no text from the model")
        return {"ok": False, "error": "model_failed"}
    return {"ok": True, "text": reply.text, "count": result["count"]}
