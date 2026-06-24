"""ToolDispatcher — ينفذ tool calls من Gemini.

يأخذ اسم الـ tool والـ args، يبحث في الـ registry،
ويستدعي الـ Python handler.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from app.agent.tool_health import record_call as _record_health
from app.agent.tools.registry import ToolRegistry, get_registry

logger = logging.getLogger(__name__)


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
