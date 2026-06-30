"""ToolDispatcher — ينفذ tool calls من Gemini.

يأخذ اسم الـ tool والـ args، يبحث في الـ registry،
ويستدعي الـ Python handler.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from app.agent.guards import DESTRUCTIVE_TOOLS
from app.agent.tool_health import record_call as _record_health
from app.agent.tools.registry import ToolRegistry, get_registry

logger = logging.getLogger(__name__)

# Deterministic confirmation guard. task_delete and reminder_delete run their own
# confirmation flows, so they are excluded here to avoid double-asking; the rest
# execute immediately, so the dispatcher forces a confirmation before running them
# (unless the user already confirmed this turn — see _GUARD_CONFIRMED_FLAG).
_SELF_CONFIRMING_TOOLS = frozenset({"task_delete", "reminder_delete"})
_GUARDED_DESTRUCTIVE = frozenset(DESTRUCTIVE_TOOLS) - _SELF_CONFIRMING_TOOLS
_GUARD_CONFIRMED_FLAG = "_destructive_confirmed"

# Short Arabic action phrase per guarded tool, for the confirmation prompt.
_GUARD_SUMMARY = {
    "device_control": "تتحكم بالجهاز",
    "scene_apply": "تطبّق المشهد",
    "delete_photo": "تحذف الصورة",
    "brainstorm_delete": "تحذف جلسة العصف الذهني",
    "shopping_remove": "تشيل العنصر من قائمة التسوّق",
}


def _guard_summary(tool_name: str, args: Dict[str, Any]) -> str:
    """Human confirmation phrase, enriched with a key arg when present."""
    base = _GUARD_SUMMARY.get(tool_name, "تنفّذ هذه العملية")
    hint = ""
    for key in ("label", "name", "title", "item", "device"):
        val = str((args or {}).get(key, "")).strip()
        if val:
            hint = f" «{val}»"
            break
    return base + hint


@dataclass
class DispatchContext:
    """السياق اللازم لكل tool handler."""
    user_message: str
    normalized_message: str
    session: Dict[str, Any]
    state: Any = None                          # SandyState — تجنب circular import
    mongo_db: Any = None
    create_chat_completion_fn: Optional[Callable] = None


class ToolDispatcher:
    """ينفذ tool بالاسم — Python handler."""

    def __init__(
        self,
        registry: Optional[ToolRegistry] = None,
    ) -> None:
        self.registry = registry or get_registry()

    def _guard_destructive(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: DispatchContext,
    ) -> Dict[str, Any]:
        """Store a pending that re-runs (tool_name, args) on confirm, and ask."""
        from app.agent.pending import create_pending_action

        session = context.session if isinstance(context.session, dict) else {}
        chat_id = str((getattr(context, "state", None) or {}).get("chat_id", "") or "")
        summary = _guard_summary(tool_name, args)
        session["pending_action"] = create_pending_action({
            "type": "tool_guard",
            "action": "execute",
            "tool": tool_name,
            "args": args,
            "summary": summary,
            "chat_id": chat_id,
        })
        logger.info(f"[Dispatcher] destructive guard: holding {tool_name} for confirm")
        return {"handled": True, "reply": f"متأكد إنك بدك {summary}؟ (اه/لأ)"}

    def dispatch(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: DispatchContext,
    ) -> Dict[str, Any]:
        """نفّذ tool وارجع {handled, reply, ...}.

        كل استدعاء (نجح أو فشل) يتسجّل في tool_health حتى نعرف الأداة
        المتذبذبة بدون ما نرجع نقرأ اللوقات.
        """
        tool = self.registry.get_tool(tool_name)
        if not tool:
            logger.warning(f"[Dispatcher] unknown tool: {tool_name}")
            return {"handled": False, "reply": f"أداة غير معروفة: {tool_name}"}

        # Deterministic destructive-action guard: never run one of these without an
        # explicit confirmation, regardless of what the model decided. On the first
        # pick we store a pending and ask; the confirm turn re-dispatches with the
        # flag set (see executor/pending), so this skips and the tool runs for real.
        session = getattr(context, "session", None) or {}
        if tool_name in _GUARDED_DESTRUCTIVE and not session.get(_GUARD_CONFIRMED_FLAG):
            return self._guard_destructive(tool_name, args or {}, context)

        start = time.perf_counter()
        result: Dict[str, Any]
        error_for_health: Optional[str] = None

        try:
            logger.info(f"[Tool] {tool_name} | args={list((args or {}).keys())}")
            if not tool.handler:
                result = {"handled": False, "reply": f"handler غير مسجل: {tool_name}"}
                error_for_health = "handler missing"
            else:
                result = tool.handler(args or {}, context)
        except Exception as exc:
            logger.error(f"[Dispatcher] {tool_name} failed: {exc}")
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            try:
                _record_health(
                    tool_name, ok=False, latency_ms=elapsed_ms, error=str(exc),
                )
            except Exception:
                pass
            return {"handled": False, "reply": f"خطأ في تنفيذ {tool_name}."}

        # handled=True يعتبر نجاح
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        ok = bool(result.get("handled")) and error_for_health is None
        try:
            _record_health(
                tool_name,
                ok=ok,
                latency_ms=elapsed_ms,
                error=error_for_health or (None if ok else "handled=False"),
            )
        except Exception:
            pass
        return result
