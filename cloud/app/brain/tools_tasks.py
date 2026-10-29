"""The task tools: make one from talk, list, pause, resume, re-time and remove them.

A task is shown and waits for the user's yes before it is saved (`task_create` holds, and the
yes replays it with `ctx.confirmed`). It may only read and tell: its check is one of
`tasks.READ_TOOLS`, its tools within `tasks.ALLOWED` (reads only: that list is the guard).
Words that ask for money, sending in his name, publishing or deleting only make the question
say a task never does them. The tools
are offered (`TASK_SCHEMAS`, `tools.openai_tools`) and answer only for an account with the
`tasks` switch on. Nothing here names a field of work: what to check and what is worth
telling are the user's own words.
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any, Dict, List, Optional

from app.blocks import tasks
from app.blocks.tasks import ALLOWED, READ_TOOLS, SWITCH
from app.brain import lang
from app.brain import when as W
from app.brain.ctx import TurnCtx, needs_confirmation, refused
from app.brain.matching import match_key, match_rows

# Words that ask a task to act for him: pay, transfer, buy, send in his name, publish, delete.
# They are a question, not the guard: a task's tools only read (`tasks.ALLOWED`), so none of it
# can happen whatever it is told; with these words the yes it waits for says so. An Arabic one
# counts as a word's start («سدّديلي»), an English one whole, and a phrase as it is.
_ACTS_AR = ("ادفعي", "سددي", "حولي", "اشتري", "انشري", "احذفي", "امسحي", "شيلي", "باسمي",
            "نيابه عني", "ابعتي ايميل", "ابعتي رساله")
_ACTS_EN = ("pay", "pays", "paying", "buy", "purchase", "transfer", "transfers", "publish",
            "tweet", "delete", "remove", "send money", "on my behalf", "in my name", "post on",
            "post to", "post it", "send an email", "send email")
# How soon a new task runs first, unless the user says.
FIRST_RUN = timedelta(minutes=1)

_S = {"type": "string"}
# How his results are emailed: set only from his words, never guessed (`tasks.clean_delivery`).
_HOW = {
    "notify_how": {"type": "string", "enum": [tasks.INSTANT, tasks.DAILY, tasks.EVERY],
                   "description": ("بس إذا هو حكاها: «فوراً كل ما يتغيّر» instant، «ملخص مرة باليوم "
                                   "الساعة…» daily، «بالكتير مرة كل كذا ساعة» every. ما حكى؟ خلّيها فاضية "
                                   "(only if he said it; leave it out otherwise)")},
    "notify_hours": {"type": "integer", "description": "لـ every: كل قديش ساعة"},
    "notify_at": {**_S, "description": "لـ daily: الساعة HH:MM بتوقيته"}}
TASK_SCHEMAS: List[Dict[str, Any]] = [
    {"name": "task_create",
     "description": ("اعملي مهمة بتشتغل لحالها كل فترة («كل ساعة شوفي…»، «تابعي… وقلّيلي إذا…»، "
                     "«every hour check…», «track… and tell me if…»). check_tool أداة قراءة "
                     "بمدخلات ثابتة، الكود بيقارن نتيجتها كل مرة، وإنتِ بتشتغلي بس لما تتغيّر. "
                     "بتستنى موافقته قبل الحفظ؛ instructions و notify_when بكلامه هو وبلغته. "
                     "المهمة بتقرا وبتبلّغ بس: «ذكّريني قبل يومين» بمهمة هو رسالتها، مش تذكير "
                     "(«remind me» in a task is its message, never a reminder). "
                     "ما تسألي قبل: خمّني وهو بيصحّح (never ask first: guess, he corrects)."),
     "parameters": {"type": "object", "properties": {
         "title": {**_S, "description": "اسم قصير للمهمة بكلامه"},
         "instructions": {**_S, "description": "طلبه زي ما حكاه"},
         "every_minutes": {"type": "integer", "description": "كل قديش دقيقة («كل ساعة» = 60)"},
         "check_tool": {"type": "string", "enum": list(READ_TOOLS),
                        "description": "شو بيفحص الكود كل مرة"},
         "check_args": {"type": "object", "description": "مدخلات check_tool، ثابتة"},
         "notify_when": {**_S, "description": ("شو بيستاهل تبليغ، بكلامه؛ مش امتى بيوصله: «فوراً» "
                                               "مكانها notify_how (what is worth telling, not how "
                                               "soon: «right away» is notify_how=instant)")},
         "tools": {"type": "array", "items": {"type": "string", "enum": list(ALLOWED)},
                   "description": "الأدوات اللي بتحتاجيها بالمهمة"},
         "urgent": {"type": "boolean", "description": "مستعجلة (ما بتستنى)"},
         **_HOW,
         "first_in_minutes": {"type": "integer", "description": "بعد قديش أول مرة (اختياري)"}},
         "required": ["title", "instructions", "every_minutes", "check_tool"]}},
    {"name": "task_list", "description": "المهام اللي شغّالة أو موقّفة («شو المهام الشغّالة؟»).",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "task_update",
     "description": ("وقّفي أو رجّعي أو غيّري وقت مهمة أو طريقة تبليغها («وقّفيها»، «خلّيها كل "
                     "ساعتين»، «بلّغيني فوراً»، «ابعتيلي ملخص الساعة تسعة»)؛ "
                     "خدي الـ id من task_list، والاسم بس لو مش ظاهر."),
     "parameters": {"type": "object", "properties": {
         "id": _S, "match_text": {**_S, "description": "اسم المهمة كما سمّاها"},
         "pause": {"type": "boolean"}, "resume": {"type": "boolean"},
         "every_minutes": {"type": "integer"}, **_HOW}, "required": []}},
    {"name": "task_cancel", "description": "احذفي مهمة («الغي مهمة مستقل»).",
     "parameters": {"type": "object", "properties": {
         "id": _S, "match_text": {**_S, "description": "اسم المهمة كما سمّاها"}}, "required": []}},
]


def offered(user_id: str) -> bool:
    from app.utils import flags
    return flags.on(SWITCH, user_id)


def _every(minutes: int) -> str:
    if minutes % 60 == 0:
        return lang.say("every_hours", n=minutes // 60)
    return lang.say("every_minutes", n=minutes)


def _how(delivery: Dict[str, Any]) -> str:
    if delivery["mode"] == tasks.INSTANT:
        return lang.say("delivery_instant")
    if delivery["mode"] == tasks.DAILY:
        return lang.say("delivery_daily", at=delivery["at"])
    if delivery["hours"] == 1:
        return lang.say("delivery_hourly")
    return lang.say("delivery_hours", n=delivery["hours"])


# The way, read from his own words when the model left the field out: only what he said.
_NUMBERS = {"واحد": 1, "وحده": 1, "اتنين": 2, "تنتين": 2, "تلات": 3, "تلاته": 3, "ثلاث": 3,
            "ثلاثه": 3, "اربع": 4, "اربعه": 4, "خمس": 5, "خمسه": 5, "ست": 6, "سته": 6, "سبع": 7,
            "سبعه": 7, "تمن": 8, "تمانيه": 8, "ثمانيه": 8, "تسع": 9, "تسعه": 9, "عشر": 10, "عشره": 10,
            "حدعش": 11, "احدعش": 11, "اطنعش": 12, "اتنعش": 12,
            "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
            "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
# Longest first, so «تسعه» is not read as «تسع».
_N = r"(\d{1,2}|" + "|".join(sorted(_NUMBERS, key=len, reverse=True)) + r")"
_INSTANT = re.compile(r"\b(فورا|فورن|اول ما|right away|straight away|immediately|instantly|as soon as)\b")
_SUMMARY = re.compile(r"(ملخص|summary|digest|once a day|مره باليوم|مره كل يوم)")
_AT = re.compile(r"(?:الساعه|at)\s+" + _N + r"(?:[:.](\d{2}))?\s*(am|pm|الصبح|الصباح|صباحا|المسا|مسا|مساء|"
                 r"بالليل|الليل|العصر|الضهر|الظهر)?")
_HOURS_ONLY = re.compile(r"(?:بالكتير|على الاكتر|at most|no more than)[^.؟?]*?(?:كل|every)\s+"
                         r"(?:" + _N + r"\s+)?(ساعتين|ساعات|ساعه|hours?)")
_PM = ("pm", "المسا", "مسا", "مساء", "بالليل", "الليل", "العصر")


def _number(word: str) -> int:
    return int(word) if word.isdigit() else _NUMBERS[word]


def said_delivery(words: str) -> Optional[Dict[str, Any]]:
    """The way his words ask for, or None when they ask none (then the default holds)."""
    text = " ".join(re.sub(r"[ًٌٍَُِّْـ]", "", str(words or "").lower()).split())
    for a, b in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ة", "ه"), ("ى", "ي")):
        text = text.replace(a, b)
    every = _HOURS_ONLY.search(text)
    if every:
        n = 2 if every[2] == "ساعتين" else _number(every[1]) if every[1] else 1
        return {"mode": tasks.EVERY, "hours": n}
    if _SUMMARY.search(text):
        at = _AT.search(text)
        if at:
            hour, minute = _number(at[1]), int(at[2] or 0)
            if at[3] in _PM and hour < 12:
                hour += 12
            elif at[3] in ("am", "الصبح", "الصباح", "صباحا") and hour == 12:
                hour = 0
            if hour < 24:
                return {"mode": tasks.DAILY, "at": f"{hour:02d}:{minute:02d}"}
    if _INSTANT.search(text):
        return {"mode": tasks.INSTANT}
    return None


def _delivery(args: Dict[str, Any]) -> Dict[str, Any]:
    """His way: the call's, else what his own words in the task ask for, else the default.
    ValueError when the call's cannot be read."""
    if args.get("notify_how"):
        return tasks.clean_delivery(args.get("notify_how"), args.get("notify_hours"), args.get("notify_at"))
    said = said_delivery(f"{args.get('instructions') or ''} . {args.get('notify_when') or ''}") or {}
    return tasks.clean_delivery(said.get("mode"), said.get("hours"), said.get("at"))


def _minutes(value: Any) -> Optional[int]:
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return None
    return minutes if minutes > 0 else None


def _asks_to_act(words: str) -> bool:
    tokens = match_key(words).split()
    joined = f" {' '.join(tokens)} "
    for word in (*_ACTS_AR, *_ACTS_EN):
        key = match_key(word)
        if " " in key:
            if f" {key} " in joined:
                return True
        elif any(t == key or (word in _ACTS_AR and t.startswith(key)) for t in tokens):
            return True
    return False


def task_create(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    if not offered(ctx.user_id):
        return refused("tasks are not on for this account")
    title = str(args.get("title") or "").strip()
    instructions = str(args.get("instructions") or "").strip()
    every = _minutes(args.get("every_minutes"))
    check = str(args.get("check_tool") or "")
    allowed = [str(t) for t in args.get("tools") or [check]]
    if not title or not instructions or every is None:
        return refused("title, instructions and every_minutes (above zero) are needed")
    if check not in READ_TOOLS:
        return refused(f"check_tool must read: one of {list(READ_TOOLS)}")
    if any(t not in ALLOWED for t in allowed):
        return refused(f"a task only reads and tells: its tools are within {list(ALLOWED)}; "
                       "«remind me» in a task is its own message, not a reminder")
    try:
        delivery = _delivery(args)
    except ValueError as exc:
        return refused(f"notify_how: {exc}; leave it out if he did not say how")
    if not ctx.confirmed:
        acts = _asks_to_act(f"{instructions} {args.get('notify_when') or ''}")
        return needs_confirmation(lang.say("task_confirm_reads_only" if acts else "task_confirm",
                                           title=title, every=_every(every), how=_how(delivery)))
    spec = {"instructions": instructions, "notify_when": str(args.get("notify_when") or ""),
            "probe": {"tool": check, "args": dict(args.get("check_args") or {})},
            "tools": list(dict.fromkeys([check, *allowed])), "lang": lang.current(),
            "urgent": bool(args.get("urgent")), "delivery": delivery}
    first = _minutes(args.get("first_in_minutes"))
    at = W.now_utc() + (timedelta(minutes=first) if first else FIRST_RUN)
    tid = tasks.add(title, spec, every_minutes=every, first_at=at)
    if not tid:
        return refused("not saved")
    return {"ok": True, "id": tid,
            "reply": lang.say("task_saved", title=title, every=_every(every), how=_how(delivery))}


def _rows() -> List[Dict[str, Any]]:
    return tasks.running()


def task_list(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    if not offered(ctx.user_id):
        return refused("tasks are not on for this account")
    rows = _rows()
    if not rows:
        return {"ok": True, "tasks": [], "reply": lang.say("task_none")}
    listed = [{"id": r["id"], "title": r.get("text", ""), "every_minutes": tasks.every_minutes(r),
               "paused": r.get("status") == "paused", "delivery": tasks.how(r)} for r in rows]
    lines = [lang.say("task_row_paused" if t["paused"] else "task_row", title=t["title"],
                      every=_every(t["every_minutes"] or 1), how=_how(t["delivery"])) for t in listed]
    return {"ok": True, "tasks": listed, "reply": "\n".join(lines)}


def _one(args: Dict[str, Any]) -> Dict[str, Any]:
    rows = _rows()
    if args.get("id"):
        row = next((r for r in rows if r["id"] == str(args["id"])), None)
        return {"row": row} if row else refused("no task has that id", reply=lang.say("task_not_found"))
    picked = match_rows(str(args.get("match_text") or ""), [{**r, "text": r.get("text", "")} for r in rows])
    if picked["status"] == "matched" and picked.get("tier") != "fuzzy":
        return {"row": picked["row"]}
    if picked["status"] == "ambiguous":
        return refused("more than one task matches; ask which", matches=[
            {"id": r["id"], "title": r.get("text", "")} for r in picked["matches"]])
    return refused("no task by that name", reply=lang.say("task_not_found"))


def task_update(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    if not offered(ctx.user_id):
        return refused("tasks are not on for this account")
    found = _one(args)
    if "row" not in found:
        return found
    row, said = found["row"], []
    if args.get("pause"):
        tasks.pause(row["id"])
        said.append(lang.say("task_paused", title=row.get("text", "")))
    if args.get("resume"):
        tasks.resume(row["id"])
        said.append(lang.say("task_resumed", title=row.get("text", "")))
    every = _minutes(args.get("every_minutes"))
    if every:
        tasks.set_every(row["id"], every)
        said.append(lang.say("task_every", title=row.get("text", ""), every=_every(every)))
    if args.get("notify_how"):
        try:
            delivery = _delivery(args)
        except ValueError as exc:
            return refused(f"notify_how: {exc}")
        tasks.set_delivery(row["id"], delivery)
        said.append(lang.say("task_delivery", title=row.get("text", ""), how=_how(delivery)))
    if not said:
        return refused("say pause, resume, every_minutes or notify_how", reply=lang.say("nothing_changed"))
    return {"ok": True, "changed": 1, "reply": "\n".join(said)}


def task_cancel(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    if not offered(ctx.user_id):
        return refused("tasks are not on for this account")
    found = _one(args)
    if "row" not in found:
        return found
    if not tasks.remove(found["row"]["id"]):
        return refused("not removed")
    return {"ok": True, "changed": 1,
            "reply": lang.say("task_removed", title=found["row"].get("text", ""))}
