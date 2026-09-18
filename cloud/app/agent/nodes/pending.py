"""pending_node: ينفّذ الـ pending action الحالي.

Wrapper يحوّل SandyState للـ session القديمة ويستدعي execute_pending_action().

الحالات: confirmation (نعم/لا)، clarification (إجابة سؤال)،
selection (اختيار رقم)، destructive (تأكيد قبل حذف).

When the pending handlers decline the message (``handled`` false, no reply —
the user moved on to something else), the turn continues on the normal path
instead of ending in an apology.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.agent.graph.state import SandyState, merge_state
from app.agent.tool_result import result_ok
from app.agent.executor.pending_execution import execute_pending_action
from app.utils.session import build_session_from_state as _build_session_from_state

logger = logging.getLogger(__name__)


def _extract_results_from_session(
    session: Dict[str, Any],
    original_pending: Dict[str, Any],
) -> Dict[str, Any]:
    """يستخرج pending_state المحدث وarchived من الـ session بعد التنفيذ."""
    new_pending = session.get("pending_action")
    # consumed pending → treat as cleared so it doesn't leak into next request
    if isinstance(new_pending, dict) and new_pending.get("consumed_at"):
        new_pending = None
    archived = session.get("archived_pending") or []

    # إذا الـ pending اتغير → ابنِ archived list محدث
    if isinstance(archived, dict):
        archived = [archived]

    return {
        "pending_state": new_pending,
        "pending_archived": archived,
    }


def _noop_save(*args, **kwargs) -> None:
    """save_session_fn وهمية — الـ graph بيحفظ الـ pending بنفسه."""


_INTENT_TO_PENDING_RESPONSE = {
    "pending.confirm": "confirm",
    "pending.reject": "reject",
    "pending.select_option": "confirm",
}


def pending_node(state: SandyState) -> SandyState:
    """Pipeline node: ينفذ الـ pending action الحالي.

    يستدعي execute_pending_action() الموجودة عبر session مؤقت.
    """

    original_pending = state.get("pending_state") or {}

    # An expired question must not be glued onto today's message.
    from app.agent.pending import get_valid_pending_action
    if original_pending and get_valid_pending_action(
            {"pending_action": dict(original_pending)}) is None:
        return _continue_without_pending(merge_state(state, {"pending_state": None}))

    # clarification await: المستخدم أجاب على سؤال توضيحي
    if (
        original_pending.get("type") == "clarification"
        and original_pending.get("action") == "await_clarification"
    ):
        original_message = str(original_pending.get("original_message") or "").strip()
        user_answer = str(state.get("message") or "").strip()
        combined = (
            f"{original_message} — {user_answer}" if original_message else user_answer
        )

        # أعد الـ state بدون pending وبالرسالة المدمجة
        new_state = merge_state(
            state,
            {
                "message": combined,
                "pending_state": None,
                "requires_clarification": False,
                "routing_hint": "execute_direct",
            },
        )

        try:
            from app.agent.nodes.execute import execute_node

            return execute_node(new_state)
        except Exception as exc:
            logger.error("[pending_node] clarification re-execute failed: %s", exc)
            return merge_state(
                state,
                {
                    "pending_state": None,
                    "final_response": "حصل خطأ، حاول مرة ثانية.",
                    "execution_result": {
                        "handled": False,
                        "reply": "حصل خطأ، حاول مرة ثانية.",
                        "source": "pending_node_clarify",
                    },
                },
            )

    session = _build_session_from_state(state)

    # Map Gemini intent → response_intent to skip regex classifier
    intent_hint = _INTENT_TO_PENDING_RESPONSE.get(state.get("intent") or "", "")

    try:
        from app.db import get_db

        # From the one handle every store reads. This used to be
        # `getattr(executor.deps, "mongo_db", None)` — an attribute `deps` has
        # never had, so it was always None and only worked because each store
        # falls back to `get_db()` itself.
        mongo_db = get_db()
        create_chat_completion_fn = None
        try:
            from app.agent.nodes.execute import _get_chat_completion_fn
            create_chat_completion_fn = _get_chat_completion_fn()
        except Exception:
            logger.debug("ignoring non-critical error", exc_info=True)

        result = execute_pending_action(
            user_message=state["message"],
            session=session,
            session_file=None,
            mongo_db=mongo_db,
            tasks_file=None,
            save_session_fn=_noop_save,
            create_chat_completion_fn=create_chat_completion_fn,
            intent_hint=intent_hint,
        )

    except Exception as exc:
        logger.exception("[pending_node] execute_pending_action failed: %s", exc)
        result = {"handled": False, "reply": "حصل خطأ، حاول مرة ثانية."}

    handled = result.get("handled", False)
    reply = result.get("reply") or ""
    reply_markup = result.get("reply_markup")

    pending_updates = _extract_results_from_session(session, original_pending)

    updates: Dict[str, Any] = {
        **pending_updates,
        "execution_result": {
            "handled": handled,
            # يتنسخ زي `execute_node` بالضبط. من غيره كل رفض جاي من
            # `executor/pending/**` بينزل لـ `handled` لحاله بهالمسار،
            # فبيصير معنى `execution_result["ok"]` بيفرق حسب مين العقدة
            # اللي طلّعته — وهاد أسوأ من ما يكون مش موجود.
            "ok": result_ok(result),
            "reply": reply,
            "reply_markup": reply_markup,
            "source": "pending_node",
        },
    }

    if reply:
        updates["final_response"] = reply
    elif not handled:
        # Not an answer to the pending question: handle it as a new message.
        return _continue_without_pending(merge_state(state, pending_updates))

    return merge_state(state, updates)


def _continue_without_pending(state: SandyState) -> SandyState:
    """Run the turn as if no pending had caught it."""
    if state.get("requires_clarification"):
        from app.agent.nodes.clarify import clarify_node
        return clarify_node(state)
    from app.agent.nodes.execute import execute_node
    return execute_node(state)
