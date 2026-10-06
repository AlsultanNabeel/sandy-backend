"""The brain's tools on the live voice session (Gemini Live calls them directly).

Voice has no text turn for the server to read a yes from, so it declares one
extra tool, ``confirm``: the model passes the user's own words and the same
yes/no resolver as chat decides. Held actions wait on the pending store's "voice"
thread.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

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
        if again is None:
            return _ask_next(held, chat_id, {
                "handled": True, "ok": False,
                "reply": f"[لم يُنفَّذ] ما فهمت جوابه مرتين، فما عملت: {held['summary']}."})
        P.save(VOICE_THREAD, chat_id, db, again)
        return {"handled": True,
                "reply": f"ما فهمت اه ولا لأ — اسأليه مرة تانية: {confirm.question(held['summary'])}"}
    out = ({"handled": True, "reply": confirm.CANCELLED_REPLY} if said == "no"
           else _tagged(confirm.run_held(held, TurnCtx(user_id=chat_id, source="voice"))))
    if rest:
        out["reply"] += "\nقال كمان إشي بعد جوابه: نفّذيه هلأ."
    return _ask_next(held, chat_id, out)


def _ask_next(held: Dict[str, Any], chat_id: str, out: Dict[str, Any],
              waiting: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """``held`` is answered or let go: ``waiting`` (what the answer still waits for), then
    what waited behind it, is saved and asked; nothing left clears the hold."""
    nxt = confirm.then(waiting, confirm.following(held))
    P.save(VOICE_THREAD, chat_id, get_db(), nxt)
    if nxt is not None:
        out["reply"] += f"\nلسا ما نفّذت — اسأليه: {confirm.ask(nxt)}"
    return out


def _answer_choice(answer: str, held: Dict[str, Any], chat_id: str) -> Dict[str, Any]:
    """«الأولى» after «أي وحدة؟», as in chat: each chosen row is acted on, and what still
    needs a yes waits as one question."""
    if confirm.answer(answer) == "no":
        return _ask_next(held, chat_id, {"handled": True, "reply": confirm.CANCELLED_REPLY})
    ids, rest = confirm.pick(answer, held.get("candidates") or [])
    if ids is None:
        again = confirm.asked_again(held)
        if again is None:
            return _ask_next(held, chat_id, {
                "handled": True, "ok": False,
                "reply": "[لم يُنفَّذ] ما فهمت أي وحدة مرتين، فما عملت إشي."})
        P.save(VOICE_THREAD, chat_id, get_db(), again)
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
    if rest:
        results.append("قال كمان إشي بعد اختياره: نفّذيه هلأ.")
    return _ask_next(held, chat_id, {"handled": True, "reply": "\n".join(results)}, waiting)


def dispatch(name: str, args: Dict[str, Any], chat_id: str) -> Dict[str, Any]:
    """Run one voice tool call for ``chat_id`` (the caller sets the tenant context)."""
    if name == "confirm":
        return _answer_held(str((args or {}).get("answer") or ""), chat_id)
    result = tools.execute(name, args or {}, TurnCtx(user_id=chat_id, source="voice"))
    if result.get("needs_confirmation") or result.get("needs_choice"):
        db = get_db()
        # Two deletes in one breath wait as one: the question names both, one yes runs both.
        # A «which one?» waits behind what is already asked, as in chat.
        held = confirm.add(confirm.live(P.load(VOICE_THREAD, chat_id, db)),
                           name, args or {}, result)
        P.save(VOICE_THREAD, chat_id, db, held)
        logger.info("[voice_ws] brain %s is waiting for the user", name)
        # Not done yet and not refused: the pending is live (C10); `confirm` takes the answer.
        return {"handled": True, "reply": f"لسا ما نفّذت — اسأليه:\n{confirm.ask(held)}"}
    return _tagged(result)
