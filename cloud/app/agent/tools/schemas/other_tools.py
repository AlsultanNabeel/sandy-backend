"""Research + Image + Utility tools — schemas + adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from app.agent.tools.dispatcher import DispatchContext

def _NOOP_SAVE(*a, **kw): return None


def _call_dispatch(action_type: str, params: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    from app.agent.executor.dispatch import execute_operational_action
    return execute_operational_action(
        action_type=action_type,
        params=params,
        user_message=ctx.user_message,
        normalized_user_message=ctx.normalized_message,
        session=ctx.session,
        session_file=None,
        mongo_db=ctx.mongo_db,
        tasks_file=None,
        create_chat_completion_fn=ctx.create_chat_completion_fn,
        save_session_fn=_NOOP_SAVE,
    )


# Research

def research_web(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    return _call_dispatch("research", args, ctx)

def research_places(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    return _call_dispatch("places", args, ctx)


# Image

def image_generate(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    return _call_dispatch("image", {"action": "generate", **args}, ctx)

def image_describe(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    return _call_dispatch("image", {"action": "describe", **args}, ctx)

def image_edit(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    return _call_dispatch("image_edit", {"prompt": args.get("prompt", "")}, ctx)


# Utility

def get_time(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    return _call_dispatch("time", {}, ctx)

def get_weather(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    return _call_dispatch("weather", args, ctx)


# Schemas

OTHER_TOOLS = [
    # Research
    {
        "name": "research_web",
        "description": (
            "ابحث في الويب — دائماً لما يقول 'ابحث/شو آخر أخبار'، أو السؤال عن "
            "أخبار أو أسعار أو أحداث جارية أو معلومة بتتغير مع الوقت. "
            "لا تستخدم chat_respond بدلها."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "نص البحث"},
                "count": {"type": "integer", "description": "عدد النتائج (افتراضي 5)"},
            },
            "required": ["query"],
        },
        "handler": research_web,
    },
    {
        "name": "research_places",
        "description": "ابحث عن أماكن قريبة أو معلومات مكان",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "اسم المكان أو النوع"}},
            "required": ["query"],
        },
        "handler": research_places,
    },
    # Image
    {
        "name": "image_generate",
        "description": (
            "ولّد صورة جديدة: 'اعملي/حطي/ضيفي/ارسمي/صمّمي/جيبيلي صورة...'، "
            "'افتحي صورة' لما السياق إنشاء، أو نسخة ثانية/variation من صورة سابقة. "
            "استدعيها دائماً لطلب صورة، حتى لو انحكى عن صورة قبل."
        ),
        "parameters": {
            "type": "object",
            "properties": {"prompt": {"type": "string", "description": "وصف الصورة المطلوبة"}},
            "required": ["prompt"],
        },
        "handler": image_generate,
    },
    {
        "name": "image_describe",
        "description": "وصف/تحليل صورة موجودة (المستخدم رفع صورة وسأل 'شو فيها'، 'اوصفها')",
        "parameters": {
            "type": "object",
            "properties": {"question": {"type": "string", "description": "سؤال عن الصورة"}},
            "required": [],
        },
        "handler": image_describe,
    },
    {
        "name": "image_edit",
        "description": (
            "عدّل آخر صورة (مولّدة أو مرفوعة) بطلب صريح: 'خلّيها كذا'، "
            "'غيّر لون/خلفية'، 'شيل/زيد...'. النسخة الثانية → image_generate."
        ),
        "parameters": {
            "type": "object",
            "properties": {"prompt": {"type": "string", "description": "وصف التعديل المطلوب"}},
            "required": ["prompt"],
        },
        "handler": image_edit,
    },
    # Utility
    {
        "name": "get_time",
        "description": "اعرض الوقت والتاريخ الحالي",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "handler": get_time,
    },
    {
        "name": "get_weather",
        "description": "اجلب حالة الطقس لمدينة",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string", "description": "اسم المدينة"}},
            "required": [],
        },
        "handler": get_weather,
    },
]
