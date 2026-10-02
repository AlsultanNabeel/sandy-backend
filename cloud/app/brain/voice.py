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
    "description": ("جواب المستخدم على سؤال سألتيه: تأكيد (اه/لأ) أو أي وحدة من القائمة "
                    "(«الأولى»، «التنتين»). مرّري كلامه زي ما قاله بالضبط."),
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
    if held.get("action") == confirm.CHOOSE:
        return _answer_choice(answer, held, chat_id)
    said, rest = confirm.read(answer, held)
    if said == "other":
        # Asked once more, as in chat; a second unclear answer lets it go (C10: say so).
        again = confirm.asked_again(held)
        P.save(VOICE_THREAD, chat_id, db, again)
        if again is None:
            return {"handled": True, "ok": False,
                    "reply": f"[لم يُنفَّذ] ما فهمت جوابه مرتين، فما عملت: {held['summary']}."}
        return {"handled": True,
                "reply": f"ما فهمت اه ولا لأ — اسأليه مرة تانية: {confirm.question(held['summary'])}"}
    P.save(VOICE_THREAD, chat_id, db, None)
    out = ({"handled": True, "reply": confirm.CANCELLED_REPLY} if said == "no"
           else _tagged(confirm.run_held(held, TurnCtx(user_id=chat_id, source="voice"))))
    if rest:
        out["reply"] += "\nقال كمان إشي بعد جوابه: نفّذيه هلأ."
    return out


def _answer_choice(answer: str, held: Dict[str, Any], chat_id: str) -> Dict[str, Any]:
    """«الأولى» after «أي وحدة؟», as in chat: each chosen row is acted on, and what still
    needs a yes waits as one question."""
    db = get_db()
    if confirm.answer(answer) == "no":
        P.save(VOICE_THREAD, chat_id, db, None)
        return {"handled": True, "reply": confirm.CANCELLED_REPLY}
    ids = confirm.pick(answer, held.get("candidates") or [])
    if ids is None:
        again = confirm.asked_again(held)
        P.save(VOICE_THREAD, chat_id, db, again)
        if again is None:
            return {"handled": True, "ok": False,
                    "reply": "[لم يُنفَّذ] ما فهمت أي وحدة مرتين، فما عملت إشي."}
        return {"handled": True,
                "reply": f"ما فهمت أي وحدة — اسأليه مرة تانية:\n{confirm.choice_question(held['candidates'])}"}
    name = held.get("tool", "")
    base = {k: v for k, v in (held.get("args") or {}).items() if k not in ("match_text", "all_matching")}
    waiting, results = None, []
    for row_id in ids:
        args = {**base, "id": row_id}
        result = tools.execute(name, args, TurnCtx(user_id=chat_id, source="voice"))
        if result.get("needs_confirmation"):
            waiting = confirm.with_step(waiting, name, args, result["summary"])
        else:
            results.append(_tagged(result)["reply"])
    P.save(VOICE_THREAD, chat_id, db, waiting)
    if waiting is not None:
        results.append(f"لسا ما نفّذت — اسأليه: {confirm.question(waiting['summary'])}")
    return {"handled": True, "reply": "\n".join(results)}


def dispatch(name: str, args: Dict[str, Any], chat_id: str) -> Dict[str, Any]:
    """Run one voice tool call for ``chat_id`` (the caller sets the tenant context)."""
    if name == "confirm":
        return _answer_held(str((args or {}).get("answer") or ""), chat_id)
    result = tools.execute(name, args or {}, TurnCtx(user_id=chat_id, source="voice"))
    if result.get("needs_confirmation"):
        db = get_db()
        # Two deletes in one breath wait as one: the question names both, one yes runs both.
        held = confirm.with_step(confirm.live(P.load(VOICE_THREAD, chat_id, db)),
                                 name, args or {}, result["summary"])
        P.save(VOICE_THREAD, chat_id, db, held)
        logger.info("[voice_ws] brain %s is waiting for a confirmation", name)
        # Not done yet and not refused: the pending is live (C10).
        return {"handled": True,
                "reply": f"لسا ما نفّذت — اسأليه: {confirm.question(held['summary'])}"}
    if result.get("needs_choice"):
        P.save(VOICE_THREAD, chat_id, get_db(),
               confirm.hold_choice(name, args or {}, result["candidates"]))
        # Not done and not refused: she asks which, and `confirm` takes the answer.
        return {"handled": True,
                "reply": f"لسا ما نفّذت — اسأليه:\n{confirm.choice_question(result['candidates'])}"}
    return _tagged(result)
