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

def cost_report(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    return _call_dispatch("cost", args, ctx)

def github_info(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    return _call_dispatch("github", args, ctx)

def heroku_info(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    return _call_dispatch("heroku", args, ctx)


# Schemas

OTHER_TOOLS = [
    # Research
    {
        "name": "research_web",
        "description": (
            "ابحث في الويب عن معلومات حقيقية وحديثة. "
            "استخدم هذه الأداة دائماً عندما: "
            "(١) المستخدم يقول 'ابحث' أو 'بحث' أو 'وين' أو 'شو آخر أخبار' أو 'أخبار', "
            "(٢) السؤال عن أحداث جارية أو أخبار أو أسعار أو تطورات حديثة, "
            "(٣) المعلومة تتغير مع الوقت ولا يمكن الإجابة من الذاكرة بدقة. "
            "لا تستخدم chat_respond بدلاً منها لأسئلة البحث."
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
            "ولّد صورة جديدة بالذكاء الاصطناعي. استخدم هذه الأداة لما "
            "الأونر يطلب إنشاء صورة بأي من هذه الأفعال + كلمة 'صورة':\n"
            "- 'اعملي صورة لـ...' / 'اعمليلي صورة كذا'\n"
            "- 'حطي صورة عن...' / 'حطيلي صورة'\n"
            "- 'ضيفي صورة...' / 'ضيفيلي صورة'\n"
            "- 'افتحي صورة...' (لما السياق يدل على إنشاء)\n"
            "- 'ولّدي/ارسمي/صمّمي/جيبيلي صورة...'\n"
            "- طلب 'نسخة ثانية / variation' من صورة سابقة\n\n"
            "🚨 استدعي هاد الـ FC **دائماً** لطلبات إنشاء الصور — حتى لو "
            "STM فيه محادثة سابقة عن صورة. لا تردّي شات بدون استدعاء."
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
            "عدّل الصورة الأخيرة (Sandy ولّدها أو المستخدم رفعها). "
            "استخدم فقط لما المستخدم يطلب تعديل صريح: "
            "'خلّيها كذا', 'عدّل الصورة', 'غيّر لون/خلفية', 'شيل/زيد...'. "
            "لا تستخدمه لـ variation/نسخة ثانية — استخدم image_generate لهذه الحالات."
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
    {
        "name": "cost_report",
        "description": "عرض تقرير تكاليف الخدمات (Azure/Heroku/OpenAI...)",
        "parameters": {
            "type": "object",
            "properties": {"provider": {"type": "string", "description": "all|azure|heroku|openai"}},
            "required": [],
        },
        "handler": cost_report,
    },
    {
        "name": "github_info",
        "description": "اعرض معلومات من GitHub (commits/issues/PRs)",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "commits|issues|pull_requests|stats"},
                "repo": {"type": "string", "description": "اسم الـ repo"},
            },
            "required": [],
        },
        "handler": github_info,
    },
    {
        "name": "heroku_info",
        "description": "اعرض حالة Heroku (logs/status/hours)",
        "parameters": {
            "type": "object",
            "properties": {"action": {"type": "string", "description": "logs|status|hours|diagnose"}},
            "required": [],
        },
        "handler": heroku_info,
    },
]
