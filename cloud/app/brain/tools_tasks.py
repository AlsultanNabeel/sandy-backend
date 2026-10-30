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
     "description": ("وقّفي أو رجّعي أو غيّري وقت مهمة أو طريقة تبليغها أو شو بتعمل («وقّفيها»، "
                     "«خلّيها كل ساعتين»، «بلّغيني فوراً»، «ابعتيلي ملخص الساعة تسعة»، «خلّيها تتابع "
                     "الفضة بدل الدهب»: instructions بكلامه، ومعها check_tool و check_args الجداد)؛ "
                     "تغيير شو بتعمل بيستنى موافقته. خدي الـ id من task_list، والاسم بس لو مش ظاهر."),
     "parameters": {"type": "object", "properties": {
         "id": _S, "match_text": {**_S, "description": "اسم المهمة كما سمّاها"},
         "pause": {"type": "boolean"}, "resume": {"type": "boolean"},
         "every_minutes": {"type": "integer"},
         "title": {**_S, "description": "اسم جديد، بس إذا غيّره"},
         "instructions": {**_S, "description": ("بس إذا غيّر شو بتعمل المهمة، بكلامه الجديد؛ "
                                                  "للتوقيت أو التوقيف أو التبليغ لا تحطيها "
                                                  "(only when he changes what it does)")},
         "check_tool": {"type": "string", "enum": list(READ_TOOLS),
                        "description": "الفحص الجديد مع instructions الجديدة"},
         "check_args": {"type": "object", "description": "مدخلات check_tool الجديد، ثابتة"},
         "language": {"type": "string", "enum": [lang.AR, lang.EN],
                      "description": "لغة إيميلاتها ونتائجها، بس إذا طلب يغيّرها («خلّي إيميلاتها بالإنجليزي»)"},
         **_HOW}, "required": []}},
    {"name": "task_cancel", "description": ("احذفي مهمة من اللي بتشتغلي فيها لحالك (بتطلع بـ task_list) نهائياً، "
                                            "بس إذا قال احذف أو الغي («الغي مهمة مستقل»). عنصر بقائمة مهامه "
                                            "(«احذفي مهمة الجيم») هو list_delete، مش هون. «وقّفيها»، «pause it» "
                                            "مش حذف: هاد task_update مع pause. (Only a task you run on your "
                                            "own; a to-do item is list_delete.)"),
     "parameters": {"type": "object", "properties": {
         "id": _S, "match_text": {**_S, "description": "اسم المهمة كما سمّاها"}}, "required": []}},
]


def offered(user_id: str) -> bool:
    from app.utils import flags
    return flags.on(SWITCH, user_id)


def _span(n: int, unit: str) -> str:
    """«دقيقة»، «ساعتين»، «3 ساعات»، «12 ساعة»; «hour», «2 hours»."""
    size = "one" if n == 1 else "two" if n == 2 else "few" if n <= 10 else "many"
    return lang.say(f"span_{size}_{unit}", n=n)


def _every(minutes: int) -> str:
    """«كل دقيقة»، «كل ساعتين»، «كل يوم»; «every minute», «every 2 hours»."""
    minutes = max(int(minutes or 1), 1)
    if minutes % 1440 == 0:
        return lang.say("every_span", span=_span(minutes // 1440, "day"))
    if minutes % 60 == 0:
        return lang.say("every_span", span=_span(minutes // 60, "hour"))
    return lang.say("every_span", span=_span(minutes, "minute"))


def _how(delivery: Dict[str, Any]) -> str:
    if delivery["mode"] == tasks.INSTANT:
        return lang.say("delivery_instant")
    if delivery["mode"] == tasks.DAILY:
        return lang.say("delivery_daily", at=delivery["at"])
    if delivery["hours"] == 1:
        return lang.say("delivery_hourly")
    return lang.say("delivery_hours", span=_span(delivery["hours"], "hour"))


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


# The words of the way he is told, taken out of what the task tells (they are its delivery).
_WAY_WORDS = re.compile(r"(?:\b(?:و?بلغيني|و?قليلي|و?نبهيني|tell me|notify me|let me know)\s+)?"
                        r"(?:\bفورا\b|\bفورن\b|right away|straight away|immediately|instantly)",
                        re.IGNORECASE)


def without_way(words: str) -> str:
    """``words`` without how he is told («وبلّغيني فوراً», «right away»)."""
    text = re.sub(r"[ًٌٍَُِّْـ]", "", str(words or ""))
    for a, b in (("أ", "ا"), ("إ", "ا"), ("آ", "ا")):
        text = text.replace(a, b)
    return " ".join(_WAY_WORDS.sub(" ", text).split()).strip(" ،,.")


def _delivery(args: Dict[str, Any]) -> Dict[str, Any]:
    """His way: the call's, else what his own words in the task ask for, else the default.
    ValueError when the call's cannot be read."""
    if args.get("notify_how"):
        return tasks.clean_delivery(args.get("notify_how"), args.get("notify_hours"), args.get("notify_at"))
    said = said_delivery(f"{args.get('instructions') or ''} . {args.get('notify_when') or ''}") or {}
    return tasks.clean_delivery(said.get("mode"), said.get("hours"), said.get("at"))


def edit_summary(row: Dict[str, Any], *, title: str, instructions: str, every: int,
                 delivery: Dict[str, Any]) -> str:
    """The question a change of what a task does waits on, the same from talk and the screen."""
    acts = _asks_to_act(f"{instructions} {(row.get('payload') or {}).get('notify_when') or ''}")
    return lang.say("task_edit_confirm_reads_only" if acts else "task_edit_confirm", title=title,
                    every=_every(every), instructions=instructions, how=_how(delivery))


_CHECK = (
    "A task Sandy runs on her own is checked by one read tool with fixed arguments, run by code "
    "each time and compared with the last run. Given the task's words, answer only JSON "
    '{"tool": ..., "args": {...}} with tool one of: web_search {"query"} for anything on the web; '
    'recall {"list", "project", "kind", "query"} for his own lists, notes and reminders; '
    'summarize {"period": "month"} for his spending; weather {"city"}; device_state {}. '
    "Keep his words for the query.")


def derive_check(instructions: str, user_id: str) -> Optional[Dict[str, Any]]:
    """The check new words need (the Tasks screen has no model of its own): one read tool and
    its arguments, or None when none could be read from the answer."""
    import json

    from app.brain import background
    try:
        resp = background.call("task_check", [{"role": "system", "content": _CHECK},
                                              {"role": "user", "content": instructions}],
                               priority=background.DIRECT, user_id=user_id, max_tokens=150,
                               temperature=0, response_format={"type": "json_object"})
        found = json.loads(resp.choices[0].message.content or "")
    except (ValueError, OSError, RuntimeError, AttributeError, IndexError):
        return None
    tool, args = (found.get("tool"), found.get("args")) if isinstance(found, dict) else (None, None)
    if tool not in READ_TOOLS or not isinstance(args, dict):
        return None
    return {"tool": tool, "args": args}


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
    spec = {"instructions": instructions, "notify_when": without_way(str(args.get("notify_when") or "")),
            "probe": {"tool": check, "args": dict(args.get("check_args") or {})},
            "tools": list(dict.fromkeys([check, *allowed])), "lang": lang.current(),
            "urgent": bool(args.get("urgent")), "delivery": delivery}
    # It runs once now (`task_runner.start`), so its next run is a whole interval away.
    first = _minutes(args.get("first_in_minutes"))
    tid = tasks.add(title, spec, every_minutes=every,
                    first_at=W.now_utc() + timedelta(minutes=first or every))
    if not tid:
        return refused("not saved")
    from app.brain import task_diff, task_runner
    found = task_runner.start(tid, ctx.user_id)
    if found is None:
        reply = lang.say("task_started_blind", title=title, every=_every(every))
    else:
        reply = lang.say("task_started", title=title, every=_every(every),
                         state=task_diff.describe(found), how=_how(delivery))
    return {"ok": True, "id": tid, "reply": reply}


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
    return refused("no task you run on your own by that name; a to-do item on his lists is "
                   "list_update or list_delete", reply=lang.say("task_not_found"))


def task_update(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    if not offered(ctx.user_id):
        return refused("tasks are not on for this account")
    found = _one(args)
    if "row" not in found:
        return found
    row, said = found["row"], []
    rewords = any(args.get(k) for k in ("instructions", "title", "check_tool"))
    if rewords:
        # What it does changes: shown, and done only after his yes.
        check = str(args.get("check_tool") or "")
        if check and check not in READ_TOOLS:
            return refused(f"check_tool must read: one of {list(READ_TOOLS)}")
        payload = row.get("payload") or {}
        title = str(args.get("title") or row.get("text") or "").strip()
        instructions = str(args.get("instructions") or payload.get("instructions") or "").strip()
        every = _minutes(args.get("every_minutes")) or tasks.every_minutes(row) or 1
        try:
            delivery = _delivery(args) if args.get("notify_how") else tasks.how(row)
        except ValueError as exc:
            return refused(f"notify_how: {exc}")
        if not ctx.confirmed:
            return needs_confirmation(edit_summary(row, title=title, instructions=instructions,
                                                   every=every, delivery=delivery))
        probe = {"tool": check, "args": dict(args.get("check_args") or {})} if check else None
        tasks.edit(row["id"], title=title, instructions=instructions, probe=probe)
        said.append(lang.say("task_edited", title=title, instructions=instructions))
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
    if args.get("language") in (lang.AR, lang.EN):
        tasks.edit(row["id"], language=args["language"])
        said.append(lang.say("task_language", title=row.get("text", ""),
                             language=lang.say(f"language_{args['language']}")))
    if args.get("notify_how"):
        try:
            delivery = _delivery(args)
        except ValueError as exc:
            return refused(f"notify_how: {exc}")
        tasks.set_delivery(row["id"], delivery)
        said.append(lang.say("task_delivery", title=row.get("text", ""), how=_how(delivery)))
    if not said:
        return refused("say pause, resume, every_minutes, notify_how, language or instructions",
                       reply=lang.say("nothing_changed"))
    return {"ok": True, "changed": 1, "reply": "\n".join(said)}


# The words that ask for a task to be deleted; «وقّفيها», «pause it» are not among them.
_DELETE = re.compile(r"(احذف|امسح|الغي|شيل|بطل|delete|remove|cancel|get rid|drop)", re.IGNORECASE)


def task_cancel(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    if not offered(ctx.user_id):
        return refused("tasks are not on for this account")
    words = re.sub(r"[ًٌٍَُِّْـ]", "", ctx.message or "").replace("أ", "ا").replace("إ", "ا")
    if words.strip() and not _DELETE.search(words):
        # It deletes for good: only on his own words asking it.
        return refused("not deleted: he did not ask to delete it; to pause it call task_update "
                       "with pause")
    found = _one(args)
    if "row" not in found:
        return found
    if not tasks.remove(found["row"]["id"]):
        return refused("not removed")
    return {"ok": True, "changed": 1,
            "reply": lang.say("task_removed", title=found["row"].get("text", ""))}
