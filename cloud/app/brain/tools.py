"""The brain's tool table: one JSON schema per tool, enums generated from kinds.KINDS.

Adding a kind or a list is a row in `blocks/kinds.py`; the enums below follow.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional

from app.blocks.kinds import KINDS, LIST, LOG, SCHEDULE, names
from app.brain import lang
from app.brain import tools_blocks as B
from app.brain import tools_world as X
from app.brain.ctx import TurnCtx, refused
from app.brain.matching import match_key
from app.brain.when import PERIODS
from app.features import trace_store

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
    # A delete names its rows like an edit does, a few at once by `ids`, or a whole list
    # or kind by `everything` (that one waits for a yes).
    gone = {**target, "ids": {"type": "array", "items": _S, "description": "كم عنصر بالـ id مرة وحدة"},
            "everything": {"type": "boolean", "description": "كل اللي فيها (تفضية)؛ بيستنى تأكيده"}}
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
        {"name": "list_update", "description": "عدّلي/خلّصي/انقلي عنصر قائمة؛ ما بتحذف أبداً («احذفي/شيلي/امسحي» → list_delete)؛ done لعادة بيسجّل التزام اليوم. خدي الـ id من «وضعه هلأ»، والنص بس لو مش ظاهر.",
         "parameters": _obj({**target, "list": _list_enum(), "project": _S,
                             "priority": _S, "data": {**data, "description": "تفاصيل بتنضاف للعنصر (أيام العادة days، وقتها time، repeat...)"},
                             "move_to": {**_list_enum(), "description": "انقليه لهالقائمة"}, "move_to_project": _S,
                             "done": {"type": "boolean"}, "text": _S, "due": _S,
                             "no_due": {"type": "boolean", "description": "شيلي الموعد عن العنصر"},
                             "qty": {"type": "number", "description": "الكمية اللي ضايلة (لو اشترى جزء بس)"}}, [])},
        {"name": "list_delete", "description": "احذفي عنصر أو كم عنصر من قائمة («شيلي الحليب»)؛ خدي الـ id من «وضعه هلأ».",
         "parameters": _obj({**gone, "list": _list_enum(), "project": _S}, [])},
        {"name": "log_update",
         "description": ("صحّحي إشي بالسجلّ (مصروف، معلومة عنه...) (للحذف log_delete)؛ خدي الـ id من "
                         "«سجّل اليوم» أو «معلومات بتعرفيها»، والنص بس لو مش ظاهر. بلا id ولا نص: آخر "
                         "واحد من النوع. التصحيح («لا قصدي ستين مش خمسين»، «no, I meant 60 not 50») "
                         "log_update وحدة بس، وما تحذفي السطر اللي صحّحتيه."),
         "parameters": _obj({**target, "kind": {**_S, "description": "نوع السجلّ (اختياري)"},
                             "text": _S, "amount": {"type": "number"}, "data": LOG_DATA}, [])},
        {"name": "log_delete",
         "description": "احذفي إشي من السجلّ («احذفي آخر مصروف»، «انسي إني…»)؛ بلا id ولا نص: آخر واحد من النوع.",
         "parameters": _obj({**gone, "kind": {**_S, "description": "نوع السجلّ"}}, [])},
        {"name": "schedule", "description": "تذكير أو إشي بصير بوقت محدّد.",
         "parameters": _obj({"kind": _enum(SCHEDULE, "النوع"), "text": _S,
                             "in_minutes": {**_I, "description": "لوقت نسبي: بعد قديش دقيقة من هلأ («بعد نص ساعة» = 30، «شوي» = 15)"},
                             "when": {**_S, "description": "لوقت محدد: كلام المستخدم زي ما هو («عالخمسة»، «بكرا الصبح»)، أو YYYY-MM-DD HH:MM بتوقيته بدون منطقة زمنية"},
                             "recurrence": {**_S, "description": "daily|weekly|monthly|yearly أو RRULE"},
                             "before_id": {**_S, "description": "«قبل الاجتماع بربع ساعة»: id التذكير أو المهمة اللي إلها وقت"},
                             "before_minutes": {**_I, "description": "قديش دقيقة قبل before_id"},
                             "important": {"type": "boolean", "description": "منبه برنّة منبه («صحّيني»، «ضروري»، «حطيلي منبه»)"},
                             "break_focus": {"type": "boolean", "description": "المنبه بيتجاوز وضع التركيز وساعات الهدوء — بس لما يطلبها صراحة"},
                             "device": {**_S, "description": "أمر جهاز بوقت («طفّي المكيف بعد ساعة»، «turn off the AC in an hour»): الجهاز"},
                             "value": {**_S, "description": "مع device: الأمر (on/off/رقم...)"}},
                            ["kind", "text"])},
        {"name": "schedule_update", "description": "غيّري وقت/نص/تكرار تذكير، أو أجّلي واحد لسا رنّ (للإلغاء schedule_cancel)؛ خدي الـ id من «وضعه هلأ»، والنص بس لو مش ظاهر.",
         "parameters": _obj({**target,
                             "shift_minutes": {**_I, "description": "أجّلي (موجب) أو قدّمي (سالب) بهالعدد من الدقايق من وقته الحالي («أجّليه شوي» = 15، «كمان نص ساعة» = 30)"},
                             "when": {**_S, "description": "وقت جديد محدد، بنفس شكل when بأداة schedule"},
                             "text": _S,
                             "recurrence": {**_S, "description": "تكرار جديد: daily|weekly|monthly|yearly أو RRULE"},
                             "stop_repeat": {"type": "boolean", "description": "وقّفي التكرار وخلّيه مرة وحدة"},
                             "important": {"type": "boolean", "description": "true يخلّيه منبه، false يرجّعه تذكير عادي"},
                             "break_focus": {"type": "boolean", "description": "المنبه بيتجاوز وضع التركيز (true) أو لأ (false)"},
                             "skip_next": {"type": "boolean", "description": "تخطّي المرة الجاية بس («اليوم بس لا»)"}}, [])},
        {"name": "schedule_cancel", "description": "الغي تذكير أو كم تذكير («الغي تذكير الدوا»)؛ خدي الـ id من «وضعه هلأ».",
         "parameters": _obj(gone, [])},
        {"name": "summarize", "description": "جيبي كل اللي صار بفترة عشان تلخّصيه — بس لما يطلب ملخّص.",
         "parameters": _obj({"period": {"type": "string", "enum": list(PERIODS)},
                             "focus": {**_S, "description": "نوع أو قائمة أو موضوع (اختياري)"}},
                            ["period"])},
        {"name": "device_control",
         "description": ("تحكّم بجهاز مسجّل بأمر صريح فقط («طفّي نور الصالة»)؛ لعدة أجهزة devices، لغرفة "
                         "room. أمر إله وقت («طفّي المكيف بعد ساعة»، «turn off the AC in an hour») "
                         "مش لهون: هاد schedule مع device وvalue وin_minutes، والوقت ما بينحط أبداً بـ value."),
         "parameters": _obj({"device": _S,
                             "devices": {"type": "array", "items": _S, "description": "أكتر من جهاز («طفّي كل الأضواء»)"},
                             "room": {**_S, "description": "كل أجهزة الغرفة"},
                             "action": _S,
                             "value": {**_S, "description": "مستوى أو وضع («50»، «cool»)، ولا مرة وقت"},
                             "by": {**_I, "description": "تغيير نسبي للإضاءة/المستوى («خفّفي شوي» = -20، «علّي شوي» = 20)"}},
                            ["action"])},
        {"name": "device_state",
         "description": "اقري حالة الأجهزة («الضو شغّال؟»، «المكيف متّصل؟»)؛ بلا جهاز = كلهم.",
         "parameters": _obj({"device": _S, "room": _S}, [])},
        {"name": "scene_apply", "description": "طبّقي مشهد غرفة بأمر صريح فقط («جهّزي الغرفة للنوم»، «طبّقي مشهد الفيلم»).",
         "parameters": _obj({"name": _S}, ["name"])},
        {"name": "room_restore",
         "description": "رجّعي أجهزة الغرفة زي ما كانت قبل آخر مشهد، بس لما يطلب الرجوع صراحة؛ «جهّزي» أو «طبّقي» مشهد مش رجوع.",
         "parameters": _obj({}, [])},
        {"name": "web_search", "description": "ابحثي بالويب عن أخبار أو معلومة بتتغيّر.",
         "parameters": _obj({"query": _S}, ["query"])},
        {"name": "weather", "description": ("الطقس لمدينة. بلا مدينة نادي الأداة فاضية وما تسألي عن "
                                            "المدينة («كيف الجو بكرا؟»، «what's the weather like "
                                            "tomorrow?»): the user's city is saved; never ask which one."),
         "parameters": _obj({"city": {**_S, "description": "فاضية = مدينته المحفوظة"}}, [])},
        {"name": "image", "description": "ولّدي صورة من وصف.",
         "parameters": _obj({"prompt": _S}, ["prompt"])},
        {"name": "undo",
         "description": ("تراجعي عن آخر تغيير («تراجعي»، «لا رجّعيه»، «غلطت رجّعيها»)، حتى لو صار "
                         "كلام بالنص: المحذوف بيرجع زي ما كان، المعدّل بيرجع لقبل، والمضاف بينشال "
                         "(الأجهزة لأ). لعنصر معيّن match_text («رجّعي الحليب»)، ولآخر كم عنصر count."),
         "parameters": _obj({"match_text": {**_S, "description": "اسم العنصر اللي بدّه يرجع"},
                             "count": {**_I, "description": "قديش عنصر من آخر التغييرات"}}, [])},
    ]


HANDLERS: Dict[str, Callable[[Dict[str, Any], TurnCtx], Dict[str, Any]]] = {
    "remember": B.remember, "recall": B.recall, "summarize": B.summarize,
    "list_add": B.list_add, "list_update": B.list_update, "list_delete": B.list_delete,
    "schedule": B.schedule, "schedule_update": B.schedule_update,
    "schedule_cancel": B.schedule_cancel, "log_delete": B.log_delete,
    "device_control": X.device_control, "device_state": X.device_state, "scene_apply": X.scene_apply,
    "web_search": X.web_search, "weather": X.weather, "image": X.image,
    "undo": B.undo, "log_update": B.log_update, "room_restore": X.room_restore,
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


# A delete of a row the same turn corrected takes the correction back with it.
_CORRECTED_BY = {"log_delete": "log_update", "list_delete": "list_update"}


def _ids(args: Dict[str, Any]) -> set:
    return {str(i) for i in [args.get("id"), *(args.get("ids") or [])] if i}


# «now» said beside a time: the command is asked for now too, not for later only.
_NOW = {"now", "immediately", "هلق", "هسا", "هسه", "حين", "حالا", "فورا", "دغري"}


def _asked_now(message: str) -> bool:
    key = match_key(message)
    return bool(_NOW & set(key.split())) or "right away" in key


def _undoes(name: str, args: Dict[str, Any], ctx: TurnCtx) -> Optional[Dict[str, Any]]:
    """A refusal when this call takes back what an earlier call of the same turn did: «no, I
    meant 60 not 50» corrected the row and then deleted it, «turn off the AC in an hour» set
    it for later and then turned it off now (eval, 29 Oct 2026). The same command asked for
    now as well («… now and again at 11pm») is not taken back."""
    if name in _CORRECTED_BY:
        fixed = {i for n, a, ok in ctx.calls if ok and n == _CORRECTED_BY[name] for i in _ids(a)}
        if _ids(args) & fixed:
            return refused("corrected in this turn", reply=lang.say("kept_corrected"))
    if name == "device_control" and not _asked_now(ctx.message):
        devices = {str(d) for d in [args.get("device"), *(args.get("devices") or [])] if d}
        command = str(args.get("value") or args.get("action") or "")
        for n, a, ok in ctx.calls:
            if ok and n == "schedule" and str(a.get("device") or "") in devices \
                    and str(a.get("value") or a.get("action") or "") == command:
                return refused("set for later in this turn", reply=lang.say("set_for_later"))
    return None


def execute(name: str, args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    handler = HANDLERS.get(name)
    if handler is None:
        return refused(f"unknown tool {name}")
    logger.info("[brain] tool %s args=%s", name, sorted(args or {}))
    t0 = time.perf_counter()
    result = _undoes(name, dict(args or {}), ctx)
    if result is not None:
        logger.warning("[brain] tool %s refused: %s", name, result["error"])
    else:
        try:
            result = handler(dict(args or {}), ctx)
        except Exception as exc:  # noqa: BLE001 — one tool never breaks the turn
            logger.exception("[brain] tool %s raised", name)
            result = {"ok": False, "broke": True, "error": f"tool failed: {type(exc).__name__}"}
    trace_store.note_tool(name, dict(args or {}), result, ms=(time.perf_counter() - t0) * 1000)
    ctx.calls.append((name, dict(args or {}), bool(result.get("ok"))))
    ctx.results.append((name, result))
    if result.get("ok"):
        ctx.worked.append(name)
    return result
