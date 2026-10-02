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


# The extra fields, named: the voice model drops a free-form object, so an amount, a
# mood, a habit's days or a task's repeat would never reach the tool.
_N = {"type": "number"}
LOG_DATA = {"type": "object", "description": "حقول إضافية حسب النوع (اختياري)", "properties": {
    "amount": {**_N, "description": "مبلغ المصروف"},
    "category": {**_S, "description": "تصنيف المصروف: food transport shopping bills fun health other"},
    "mood": {**_S, "description": "للمزاج: stressed frustrated sad angry happy excited"},
    "book": _S, "pages": _I}}
LIST_DATA = {"type": "object", "description": "حقول إضافية حسب القائمة (اختياري)", "properties": {
    "days": {"type": "array", "items": _I, "description": "أيام العادة: 1 الأحد … 7 السبت"},
    "time": {**_S, "description": "وقت العادة HH:MM"},
    "repeat": {**_S, "description": "تكرار المهمة: daily|weekly|monthly"},
    "qty": _N, "unit": _S, "notes": _S}}


def _schemas() -> List[Dict[str, Any]]:
    data = LIST_DATA
    target = {"id": _S, "match_text": {**_S, "description": "نص العنصر كما سمّاه المستخدم"},
              "all_matching": {"type": "boolean", "description": "كل العناصر المطابقة"}}
    return [
        {"name": "remember", "description": "سجّلي إشي صار أو معلومة عن المستخدم بالسجلّ.",
         "parameters": _obj({"kind": _enum(LOG, "النوع"), "text": _S, "data": LOG_DATA},
                            ["kind", "text"])},
        {"name": "recall", "description": "دوّري بالسجلّ والقوائم والتذكيرات ورجّعي صفوف مختصرة.",
         "parameters": _obj({"query": _S,
                             "kind": {**_S, "description": "نوع سجلّ أو تذكير (اختياري)"},
                             "since": {**_S, "description": "ISO date"},
                             "rang": {"type": "boolean", "description": "التذكيرات اللي رنّت («شو فاتني؟»)، آخر يوم إذا ما في since"},
                             "until": {**_S, "description": "ISO date"},
                             "list": _list_enum(), "project": _S}, [])},
        {"name": "list_add", "description": "ضيفي عنصر لقائمة (مهمة، تسوق، هدف...). لو موجود: qty بتنضاف عكميته و due بيتحدّث.",
         "parameters": _obj({"list": _list_enum(), "project": _S, "text": _S,
                             "qty": {"type": "number", "description": "قديش («كمان حليب» = 1)"},
                             "due": {**_S, "description": "كلام المستخدم زي ما هو («بكرا 5 المسا») أو YYYY-MM-DD HH:MM بتوقيته"},
                             "priority": _S, "data": data}, ["list", "text"])},
        {"name": "list_update", "description": "عدّلي/خلّصي/احذفي/انقلي عنصر قائمة؛ done لعادة بيسجّل التزام اليوم. خدي الـ id من «وضعه هلأ»، والنص بس لو مش ظاهر.",
         "parameters": _obj({**target, "list": _list_enum(), "project": _S,
                             "priority": _S, "data": {**data, "description": "تفاصيل بتنضاف للعنصر (أيام العادة days، وقتها time، repeat...)"},
                             "move_to": {**_list_enum(), "description": "انقليه لهالقائمة"}, "move_to_project": _S,
                             "done": {"type": "boolean"}, "text": _S, "due": _S,
                             "no_due": {"type": "boolean", "description": "شيلي الموعد عن العنصر"},
                             "qty": {"type": "number", "description": "الكمية اللي ضايلة (لو اشترى جزء بس)"},
                             "delete": {"type": "boolean"}}, [])},
        {"name": "log_update",
         "description": "صحّحي أو احذفي إشي بالسجلّ (مصروف، معلومة عنه...)؛ خدي الـ id من «سجّل اليوم» أو «معلومات بتعرفيها»، والنص بس لو مش ظاهر. بلا id ولا نص: آخر واحد من النوع.",
         "parameters": _obj({**target, "kind": {**_S, "description": "نوع السجلّ (اختياري)"},
                             "text": _S, "amount": {"type": "number"}, "data": LOG_DATA,
                             "delete": {"type": "boolean"}}, [])},
        {"name": "schedule", "description": "تذكير أو إشي بصير بوقت محدّد.",
         "parameters": _obj({"kind": _enum(SCHEDULE, "النوع"), "text": _S,
                             "in_minutes": {**_I, "description": "لوقت نسبي: بعد قديش دقيقة من هلأ («بعد نص ساعة» = 30، «شوي» = 15)"},
                             "when": {**_S, "description": "لوقت محدد: كلام المستخدم زي ما هو («عالخمسة»، «بكرا الصبح»)، أو YYYY-MM-DD HH:MM بتوقيته بدون منطقة زمنية"},
                             "recurrence": {**_S, "description": "daily|weekly|monthly|yearly أو RRULE"},
                             "before_id": {**_S, "description": "«قبل الاجتماع بربع ساعة»: id التذكير أو المهمة اللي إلها وقت"},
                             "before_minutes": {**_I, "description": "قديش دقيقة قبل before_id"},
                             "important": {"type": "boolean", "description": "منبه برنّة منبه («صحّيني»، «ضروري»، «حطيلي منبه»)"},
                             "break_focus": {"type": "boolean", "description": "المنبه بيتجاوز وضع التركيز وساعات الهدوء — بس لما يطلبها صراحة"},
                             "device": {**_S, "description": "أمر جهاز بوقت («طفّي المكيف بعد ساعة»): الجهاز"},
                             "value": {**_S, "description": "مع device: الأمر (on/off/رقم...)"}},
                            ["kind", "text"])},
        {"name": "schedule_update", "description": "غيّري وقت/نص/تكرار تذكير، أجّلي واحد لسا رنّ، أو الغيه؛ خدي الـ id من «وضعه هلأ»، والنص بس لو مش ظاهر.",
         "parameters": _obj({**target,
                             "shift_minutes": {**_I, "description": "أجّلي (موجب) أو قدّمي (سالب) بهالعدد من الدقايق من وقته الحالي («أجّليه شوي» = 15، «كمان نص ساعة» = 30)"},
                             "when": {**_S, "description": "وقت جديد محدد، بنفس شكل when بأداة schedule"},
                             "text": _S, "cancel": {"type": "boolean"},
                             "recurrence": {**_S, "description": "تكرار جديد: daily|weekly|monthly|yearly أو RRULE"},
                             "stop_repeat": {"type": "boolean", "description": "وقّفي التكرار وخلّيه مرة وحدة"},
                             "important": {"type": "boolean", "description": "true يخلّيه منبه، false يرجّعه تذكير عادي"},
                             "break_focus": {"type": "boolean", "description": "المنبه بيتجاوز وضع التركيز (true) أو لأ (false)"},
                             "skip_next": {"type": "boolean", "description": "تخطّي المرة الجاية بس («اليوم بس لا»)"}}, [])},
        {"name": "summarize", "description": "جيبي كل اللي صار بفترة عشان تلخّصيه — بس لما يطلب ملخّص.",
         "parameters": _obj({"period": {"type": "string", "enum": list(PERIODS)},
                             "focus": {**_S, "description": "نوع أو قائمة أو موضوع (اختياري)"}},
                            ["period"])},
        {"name": "device_control",
         "description": "تحكّم بجهاز مسجّل بأمر صريح فقط («طفّي نور الصالة»)؛ لعدة أجهزة devices، لغرفة room.",
         "parameters": _obj({"device": _S,
                             "devices": {"type": "array", "items": _S, "description": "أكتر من جهاز («طفّي كل الأضواء»)"},
                             "room": {**_S, "description": "كل أجهزة الغرفة"},
                             "action": _S, "value": _S,
                             "by": {**_I, "description": "تغيير نسبي للإضاءة/المستوى («خفّفي شوي» = -20، «علّي شوي» = 20)"}},
                            ["action"])},
        {"name": "device_state",
         "description": "اقري حالة الأجهزة («الضو شغّال؟»، «المكيف متّصل؟»)؛ بلا جهاز = كلهم.",
         "parameters": _obj({"device": _S, "room": _S}, [])},
        {"name": "scene_apply", "description": "طبّقي مشهد غرفة بأمر صريح فقط.",
         "parameters": _obj({"name": _S}, ["name"])},
        {"name": "room_restore",
         "description": "رجّعي أجهزة الغرفة زي ما كانت قبل آخر مشهد.",
         "parameters": _obj({}, [])},
        {"name": "web_search", "description": "ابحثي بالويب عن أخبار أو معلومة بتتغيّر.",
         "parameters": _obj({"query": _S}, ["query"])},
        {"name": "weather", "description": "الطقس لمدينة.",
         "parameters": _obj({"city": {**_S, "description": "فاضية = مدينته المحفوظة"}}, [])},
        {"name": "image", "description": "ولّدي صورة من وصف.",
         "parameters": _obj({"prompt": _S}, ["prompt"])},
        {"name": "undo_last",
         "description": "ارجعي عن كل اللي عملتيه بردّك اللي قبل: اللي ضفتيه بينشال، واللي عدّلتيه أو حذفتيه أو لغيتيه بيرجع (الأجهزة لأ).",
         "parameters": _obj({}, [])},
    ]


HANDLERS: Dict[str, Callable[[Dict[str, Any], TurnCtx], Dict[str, Any]]] = {
    "remember": B.remember, "recall": B.recall, "summarize": B.summarize,
    "list_add": B.list_add, "list_update": B.list_update,
    "schedule": B.schedule, "schedule_update": B.schedule_update,
    "device_control": X.device_control, "device_state": X.device_state, "scene_apply": X.scene_apply,
    "web_search": X.web_search, "weather": X.weather, "image": X.image,
    "undo_last": B.undo_last, "log_update": B.log_update, "room_restore": X.room_restore,
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
