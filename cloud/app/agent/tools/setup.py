"""register_all_tools — يُستدعى مرة واحدة عند بدء التطبيق.

كل module في schemas/ يُعرّف قائمة tools ويسجّلها هنا.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_registered = False


def _reset_for_testing() -> None:
    """للاختبارات فقط — يعيد ضبط flag التسجيل."""
    global _registered
    _registered = False


def register_all_tools() -> None:
    """سجّل كل tools في الـ global registry. آمن للاستدعاء أكثر من مرة."""
    global _registered
    if _registered:
        return
    _registered = True

    from app.agent.tools.registry import get_registry
    from app.agent.tools.schemas.task_tools import TASK_TOOLS
    from app.agent.tools.schemas.reminder_tools import REMINDER_TOOLS
    from app.agent.tools.schemas.meta_tools import META_TOOLS
    from app.agent.tools.schemas.other_tools import OTHER_TOOLS
    from app.agent.tools.schemas.mcp_tools import MCP_TOOLS
    from app.agent.tools.schemas.goal_tools import GOAL_TOOLS
    from app.agent.tools.schemas.future_message_tools import FUTURE_MESSAGE_TOOLS
    from app.agent.tools.schemas.gift_tools import GIFT_TOOLS
    from app.agent.tools.schemas.content_share_tools import CONTENT_SHARE_TOOLS
    from app.agent.tools.schemas.self_awareness_tools import SELF_AWARENESS_TOOLS
    from app.agent.tools.schemas.photo_tools import PHOTO_TOOLS
    from app.agent.tools.schemas.brainstorm_tools import BRAINSTORM_TOOLS
    from app.agent.tools.schemas.life_tools import LIFE_TOOLS
    from app.agent.tools.schemas.device_tools import DEVICE_TOOLS

    registry = get_registry()
    count = 0

    for tool_list in (TASK_TOOLS, REMINDER_TOOLS, META_TOOLS, OTHER_TOOLS, MCP_TOOLS, GOAL_TOOLS, FUTURE_MESSAGE_TOOLS, GIFT_TOOLS, CONTENT_SHARE_TOOLS, SELF_AWARENESS_TOOLS, PHOTO_TOOLS, BRAINSTORM_TOOLS, LIFE_TOOLS, DEVICE_TOOLS):
        for t in tool_list:
            registry.register(
                name=t["name"],
                description=t["description"],
                parameters=t["parameters"],
                handler=t["handler"],
            )
            count += 1

    logger.info(f"[ToolRegistry] {count} tools registered")
