"""ToolRegistry — سجل مركزي لكل أدوات Sandy.

كل tool (Python handler) يُسجَّل هنا.
الـ FC router يجلب الـ schemas من هنا ويبعثها للـ model.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema (type/properties/required)
    handler: Optional[Callable] = None


class ToolRegistry:
    """سجل الأدوات — يخزن ويكشف كل tools لـ Gemini وللـ dispatcher."""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolDefinition] = {}

    # التسجيل

    def register(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler: Callable,
    ) -> None:
        """سجّل Python handler كـ tool."""
        self._tools[name] = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
        )
        logger.debug(f"[ToolRegistry] python: {name}")

    # البحث

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def all_names(self) -> List[str]:
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    # تصدير الـ schemas

    def get_function_declarations(self) -> List[Dict[str, Any]]:
        """يرجع schemas بصيغة function_declarations (متوافق Azure OpenAI/أي مزوّد)."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            for tool in self._tools.values()
        ]

    # وصف القدرات مع حالة كل أداة

    def describe_capabilities(self) -> List[Dict[str, Any]]:
        """وصف كل أداة مسجّلة + لقطة صحتها الحالية. لكل أداة:

            {name, description, health}

        تستخدمها meta-tool اسمها get_capabilities للرد على "شو بتقدري
        تعملي؟" و"أي قدرة معطّلة الآن؟" من مصدر واحد.
        """
        # import هون عشان نتجنب circular import: tool_health بيستوردنا
        # بشكل غير مباشر عبر الـ dispatcher.
        from app.agent import tool_health
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "health": tool_health.get_health(tool.name),
            }
            for tool in self._tools.values()
        ]


# singleton عام

_registry: Optional[ToolRegistry] = None


def get_registry() -> ToolRegistry:
    """Singleton — نفس الـ registry في كل أجزاء التطبيق."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry


def _reset_for_testing() -> None:
    """للاختبارات فقط — يمسح الـ singleton."""
    global _registry
    _registry = None
