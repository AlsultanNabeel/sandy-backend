"""The brain's tools on the live voice session (Gemini Live calls them directly).

Voice has no text turn for the server to read a yes from, so it declares one
extra tool, ``confirm``: the model passes the user's own words and the same
yes/no resolver as chat decides. Held actions wait on the pending store's "voice"
thread.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from app.brain import confirm, tools
from app.brain import pending as P
from app.brain.ctx import TurnCtx
from app.db import get_db

logger = logging.getLogger(__name__)

VOICE_THREAD = "voice"

CONFIRM_TOOL = {
    "name": "confirm",
    "description": ("جواب المستخدم على سؤال تأكيد سألتيه (اه/لأ). "
                    "مرّري كلامه زي ما قاله بالضبط."),
    "parameters": {"type": "object",
                   "properties": {"answer": {"type": "string"}},
                   "required": ["answer"]},
}


def declarations() -> List[Dict[str, Any]]:
    return tools.declarations() + [CONFIRM_TOOL]


def _tagged(result: Dict[str, Any]) -> Dict[str, Any]:
    """Everything that did not happen is marked (C10): Gemini must not confirm it."""
    text = str(result.get("reply") or "").strip()
    if result.get("ok"):
        return {"handled": True, "ok": True, "reply": text or _brief(result)}
    if result.get("broke"):
        return {"handled": False, "ok": False,
                "reply": f"[فشل التنفيذ] {text or result.get('error') or 'الأداة ما اشتغلت.'}"}
    return {"handled": True, "ok": False,
            "reply": f"[لم يُنفَّذ] {text or _brief(result)}"}


def _brief(result: Dict[str, Any]) -> str:
    keep = {k: v for k, v in result.items() if k not in ("ok", "reply", "broke")}
    return json.dumps(keep, ensure_ascii=False, default=str)[:1500]


def _answer_held(answer: str, chat_id: str) -> Dict[str, Any]:
    db = get_db()
    held = confirm.live(P.load(VOICE_THREAD, chat_id, db))
    if held is None:
        return {"handled": True, "reply": "ما في إشي مستني تأكيد."}
    said = confirm.answer(answer)
    if said == "other":
        # The held action stays alive, so this is an ask, not a refusal (C10).
        return {"handled": True,
                "reply": f"ما فهمت اه ولا لأ — اسأليه مرة تانية: {confirm.question(held['summary'])}"}
    P.save(VOICE_THREAD, chat_id, db, None)
    if said == "no":
        return {"handled": True, "reply": confirm.CANCELLED_REPLY}
    return _tagged(confirm.run_held(held, TurnCtx(user_id=chat_id, source="voice")))


def dispatch(name: str, args: Dict[str, Any], chat_id: str) -> Dict[str, Any]:
    """Run one voice tool call for ``chat_id`` (the caller sets the tenant context)."""
    if name == "confirm":
        return _answer_held(str((args or {}).get("answer") or ""), chat_id)
    result = tools.execute(name, args or {}, TurnCtx(user_id=chat_id, source="voice"))
    if result.get("needs_confirmation"):
        held = confirm.hold(name, args or {}, result["summary"])
        P.save(VOICE_THREAD, chat_id, get_db(), held)
        logger.info("[voice_ws] brain %s is waiting for a confirmation", name)
        # Not done yet and not refused: the pending is live (C10).
        return {"handled": True,
                "reply": f"لسا ما نفّذت — اسأليه: {confirm.question(result['summary'])}"}
    return _tagged(result)
