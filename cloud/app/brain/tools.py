"""The brain's tool table: one JSON schema per tool, enums generated from kinds.KINDS.

Adding a kind or a list is a row in `blocks/kinds.py`; the enums below follow.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List

from app.blocks.kinds import KINDS, LIST, LOG, SCHEDULE, names
from app.brain import tools_blocks as B
from app.brain import tools_world as X
from app.brain.ctx import TurnCtx, refused
from app.brain.when import PERIODS

logger = logging.getLogger(__name__)

_S = {"type": "string"}
_I = {"type": "integer"}


def _obj(props: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    return {"type": "object", "properties": props, "required": required}


def _enum(block: str, desc: str) -> Dict[str, Any]:
    plain = [n for n in names(block) if not n.endswith(":")]
    labels = "، ".join(f"{k.name}={k.ar}" for k in KINDS if k.block == block
                      and not k.name.endswith(":"))
    return {"type": "string", "enum": plain, "description": f"{desc} ({labels})"}


def _list_enum() -> Dict[str, Any]:
    spec = _enum(LIST, "القائمة")
    if any(n.endswith(":") for n in names(LIST)):
        spec["enum"] = spec["enum"] + ["project"]
        spec["description"] += "؛ project مع حقل project لقائمة مشروع"
    return spec


def _schemas() -> List[Dict[str, Any]]:
    data = {"type": "object", "description": "حقول إضافية حسب النوع (اختياري)"}
    target = {"id": _S, "match_text": {**_S, "description": "نص العنصر كما سمّاه المستخدم"},
              "all_matching": {"type": "boolean", "description": "كل العناصر المطابقة"}}
    return [
        {"name": "remember", "description": "سجّلي إشي صار أو معلومة عن المستخدم بالسجلّ.",
         "parameters": _obj({"kind": _enum(LOG, "النوع"), "text": _S, "data": data},
                            ["kind", "text"])},
        {"name": "recall", "description": "دوّري بالسجلّ والقوائم والتذكيرات ورجّعي صفوف مختصرة.",
         "parameters": _obj({"query": _S,
                             "kind": {**_S, "description": "نوع سجلّ أو تذكير (اختياري)"},
                             "since": {**_S, "description": "ISO date"},
                             "until": {**_S, "description": "ISO date"},
                             "list": _list_enum(), "project": _S}, [])},
        {"name": "list_add", "description": "ضيفي عنصر لقائمة (مهمة، تسوق، هدف...).",
         "parameters": _obj({"list": _list_enum(), "project": _S, "text": _S,
                             "due": {**_S, "description": "كلام المستخدم زي ما هو («بكرا 5 المسا») أو YYYY-MM-DD HH:MM بتوقيته"},
                             "priority": _S, "data": data}, ["list", "text"])},
        {"name": "list_update", "description": "عدّلي/خلّصي/احذفي عنصر قائمة؛ خدي الـ id من «وضعه هلأ»، والنص بس لو مش ظاهر.",
         "parameters": _obj({**target, "list": _list_enum(), "project": _S,
                             "done": {"type": "boolean"}, "text": _S, "due": _S,
                             "qty": {"type": "number", "description": "الكمية اللي ضايلة (لو اشترى جزء بس)"},
                             "delete": {"type": "boolean"}}, [])},
        {"name": "schedule", "description": "تذكير أو إشي بصير بوقت محدّد.",
         "parameters": _obj({"kind": _enum(SCHEDULE, "النوع"), "text": _S,
                             "in_minutes": {**_I, "description": "لوقت نسبي: بعد قديش دقيقة من هلأ («بعد نص ساعة» = 30، «شوي» = 15)"},
                             "when": {**_S, "description": "لوقت محدد: كلام المستخدم زي ما هو («عالخمسة»، «بكرا الصبح»)، أو YYYY-MM-DD HH:MM بتوقيته بدون منطقة زمنية"},
                             "recurrence": {**_S, "description": "daily|weekly|monthly|yearly أو RRULE"}},
                            ["kind", "text"])},
        {"name": "schedule_update", "description": "غيّري وقت/نص تذكير أو الغيه؛ خدي الـ id من «وضعه هلأ»، والنص بس لو مش ظاهر.",
         "parameters": _obj({**target,
                             "shift_minutes": {**_I, "description": "أجّلي (موجب) أو قدّمي (سالب) بهالعدد من الدقايق من وقته الحالي («أجّليه شوي» = 15، «كمان نص ساعة» = 30)"},
                             "when": {**_S, "description": "وقت جديد محدد، بنفس شكل when بأداة schedule"},
                             "text": _S, "cancel": {"type": "boolean"}}, [])},
        {"name": "summarize", "description": "جيبي كل اللي صار بفترة عشان تلخّصيه — بس لما يطلب ملخّص.",
         "parameters": _obj({"period": {"type": "string", "enum": list(PERIODS)},
                             "focus": {**_S, "description": "نوع أو قائمة أو موضوع (اختياري)"}},
                            ["period"])},
        {"name": "device_control",
         "description": "تحكّم بجهاز مسجّل بأمر صريح فقط («طفّي نور الصالة»).",
         "parameters": _obj({"device": _S, "action": _S, "value": _S}, ["device", "action"])},
        {"name": "scene_apply", "description": "طبّقي مشهد غرفة بأمر صريح فقط.",
         "parameters": _obj({"name": _S}, ["name"])},
        {"name": "web_search", "description": "ابحثي بالويب عن أخبار أو معلومة بتتغيّر.",
         "parameters": _obj({"query": _S}, ["query"])},
        {"name": "weather", "description": "الطقس لمدينة.",
         "parameters": _obj({"city": _S}, [])},
        {"name": "image", "description": "ولّدي صورة من وصف.",
         "parameters": _obj({"prompt": _S}, ["prompt"])},
        {"name": "undo_last",
         "description": "ارجعي عن كل اللي عملتيه بردّك اللي قبل (اللي ضفتيه بينشال، اللي عدّلتيه أو حذفتيه بيرجع).",
         "parameters": _obj({}, [])},
    ]


HANDLERS: Dict[str, Callable[[Dict[str, Any], TurnCtx], Dict[str, Any]]] = {
    "remember": B.remember, "recall": B.recall, "summarize": B.summarize,
    "list_add": B.list_add, "list_update": B.list_update,
    "schedule": B.schedule, "schedule_update": B.schedule_update,
    "device_control": X.device_control, "scene_apply": X.scene_apply,
    "web_search": X.web_search, "weather": X.weather, "image": X.image,
    "undo_last": B.undo_last,
}


def declarations() -> List[Dict[str, Any]]:
    """Plain ``{name, description, parameters}`` for Gemini Live.

    Free-form ``data`` objects are dropped: Gemini refuses an object with no properties.
    """
    out = []
    for d in _schemas():
        props = {k: v for k, v in d["parameters"]["properties"].items()
                 if not (v.get("type") == "object" and not v.get("properties"))}
        out.append({**d, "parameters": {**d["parameters"], "properties": props}})
    return out


def openai_tools() -> List[Dict[str, Any]]:
    return [{"type": "function", "function": d} for d in _schemas()]


def execute(name: str, args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    handler = HANDLERS.get(name)
    if handler is None:
        return refused(f"unknown tool {name}")
    logger.info("[brain] tool %s args=%s", name, sorted(args or {}))
    try:
        return handler(dict(args or {}), ctx)
    except Exception as exc:  # noqa: BLE001 — one tool never breaks the turn
        logger.exception("[brain] tool %s raised", name)
        return {"ok": False, "broke": True, "error": f"tool failed: {type(exc).__name__}"}
