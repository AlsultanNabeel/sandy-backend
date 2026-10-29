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
         "notify_when": {**_S, "description": "شو بيستاهل تبليغ، بكلامه"},
         "tools": {"type": "array", "items": {"type": "string", "enum": list(ALLOWED)},
                   "description": "الأدوات اللي بتحتاجيها بالمهمة"},
         "urgent": {"type": "boolean", "description": "مستعجلة (ما بتستنى)"},
         "first_in_minutes": {"type": "integer", "description": "بعد قديش أول مرة (اختياري)"}},
         "required": ["title", "instructions", "every_minutes", "check_tool"]}},
    {"name": "task_list", "description": "المهام اللي شغّالة أو موقّفة («شو المهام الشغّالة؟»).",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "task_update",
     "description": ("وقّفي أو رجّعي أو غيّري وقت مهمة («وقّفيها»، «خلّيها كل ساعتين»)؛ "
                     "خدي الـ id من task_list، والاسم بس لو مش ظاهر."),
     "parameters": {"type": "object", "properties": {
         "id": _S, "match_text": {**_S, "description": "اسم المهمة كما سمّاها"},
         "pause": {"type": "boolean"}, "resume": {"type": "boolean"},
         "every_minutes": {"type": "integer"}}, "required": []}},
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
    if not ctx.confirmed:
        acts = _asks_to_act(f"{instructions} {args.get('notify_when') or ''}")
        return needs_confirmation(lang.say("task_confirm_reads_only" if acts else "task_confirm",
                                           title=title, every=_every(every)))
    spec = {"instructions": instructions, "notify_when": str(args.get("notify_when") or ""),
            "probe": {"tool": check, "args": dict(args.get("check_args") or {})},
            "tools": list(dict.fromkeys([check, *allowed])), "lang": lang.current(),
            "urgent": bool(args.get("urgent"))}
    first = _minutes(args.get("first_in_minutes"))
    at = W.now_utc() + (timedelta(minutes=first) if first else FIRST_RUN)
    tid = tasks.add(title, spec, every_minutes=every, first_at=at)
    if not tid:
        return refused("not saved")
    return {"ok": True, "id": tid, "reply": lang.say("task_saved", title=title, every=_every(every))}


def _rows() -> List[Dict[str, Any]]:
    return tasks.running()


def task_list(args: Dict[str, Any], ctx: TurnCtx) -> Dict[str, Any]:
    if not offered(ctx.user_id):
        return refused("tasks are not on for this account")
    rows = _rows()
    if not rows:
        return {"ok": True, "tasks": [], "reply": lang.say("task_none")}
    listed = [{"id": r["id"], "title": r.get("text", ""), "every_minutes": tasks.every_minutes(r),
               "paused": r.get("status") == "paused"} for r in rows]
    lines = [lang.say("task_row_paused" if t["paused"] else "task_row", title=t["title"],
                      every=_every(t["every_minutes"] or 1)) for t in listed]
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
    if not said:
        return refused("say pause, resume or every_minutes", reply=lang.say("nothing_changed"))
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
