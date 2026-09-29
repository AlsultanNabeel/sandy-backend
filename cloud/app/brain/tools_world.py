"""Tools that act outside the blocks: thin wrappers over the existing handlers.

Actuation, research, weather and images are not reimplemented here — each
calls the same handler the old registry calls, so `command_payload` and
`tenant_owns_topic` stay the only gate on a device.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict

from app.agent.tool_result import result_failed, result_ok
from app.agent.tools.dispatcher import DispatchContext
from app.agent.tools.schemas.device_tools import device_control as _device_control
from app.agent.tools.schemas.life_tools import scene_apply as _scene_apply
from app.agent.tools.schemas.other_tools import (
    get_weather as _get_weather,
    image_generate as _image_generate,
    research_web as _research_web,
)
from app.brain.ctx import TurnCtx
from app.brain.when import _chat_fn
from app.db import get_db
from app.utils.nlp_normalizer import normalize_user_message

logger = logging.getLogger(__name__)


def _dispatch_ctx(ctx: TurnCtx) -> DispatchContext:
    return DispatchContext(
        user_message=ctx.message,
        normalized_message=normalize_user_message(ctx.message) if ctx.message else "",
        session={},
        state={"chat_id": ctx.user_id, "user_id": ctx.user_id, "message": ctx.message,
               "image_state": ctx.image_state},
        mongo_db=get_db(),
        create_chat_completion_fn=_chat_fn(),
    )


def _wrap(handler: Callable, args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    try:
        r = handler(args, _dispatch_ctx(ctx)) or {}
    except Exception as exc:  # noqa: BLE001 — a handler boundary, same as ToolDispatcher
        logger.error("[brain] %s failed: %s", getattr(handler, "__name__", "tool"), exc)
        return {"ok": False, "broke": True, "error": "tool failed"}
    if r.get("image_bytes"):
        ctx.artifacts["image_bytes"] = r["image_bytes"]
        ctx.artifacts["caption"] = r.get("caption", "")
    out: Dict[str, Any] = {"ok": result_ok(r), "reply": r.get("reply", "")}
    if result_failed(r) or not r.get("handled"):
        out.update(broke=True, error=str(r.get("error") or "tool did not run"))
    return out


def device_control(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    return _wrap(_device_control, args, ctx)


def scene_apply(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    return _wrap(_scene_apply, args, ctx)


def web_search(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    return _wrap(_research_web, args, ctx)


def weather(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    return _wrap(_get_weather, args, ctx)


def image(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    return _wrap(_image_generate, args, ctx)
