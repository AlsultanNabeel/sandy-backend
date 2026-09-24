"""Exercise every registered tool against a mongomock database.

Not a pytest file on purpose (see pytest.ini): it is a manual probe. Run it as
``python3 scripts/audit_all_tools.py`` from the repo root. For each tool it
dispatches a plausible argument set, records whether the call raised, and prints
one line per tool so a broken handler is visible by name rather than by symptom.

**It reads all three answers, not just `handled`.** It used to print
``handled ? OK : NOT-HANDLED``, and that is the one classification this probe
cannot afford: `handled` means "this tool owns the turn and here is its answer",
which a tool that caught its own exception and replied with a friendly sentence
says just as truthfully as one that worked. So the exact fault the probe exists
to find — `executor/dispatch.py::_guard` swallowing a real exception — was
counted in the OK column, and a report saying "OK: 71" was the evidence that
nothing was wrong. CONVENTIONS.md C10 and ARCHITECTURE_MAP.md §2.4 have the full
contract; `app/agent/tool_result.py` has the two readers used below.

A refusal gets its own column rather than being folded into either side: a tool
that ran and answered "no" is working, and calling that a failure is how three
customers mistyping a shopping item turn into "the shopping tool is broken".
"""
from __future__ import annotations

import os
import sys
import traceback

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_ROOT, os.path.join(_ROOT, "cloud")]

import mongomock  # noqa: E402

from app.agent.tool_result import result_failed, result_ok  # noqa: E402

os.environ.setdefault("JWT_SECRET", "audit-secret")

import app.db as appdb  # noqa: E402
from app.agent.tools.dispatcher import DispatchContext, ToolDispatcher  # noqa: E402
from app.agent.tools.registry import get_registry  # noqa: E402
from app.agent.tools.setup import register_all_tools  # noqa: E402
from app.utils import user_profiles  # noqa: E402

_CLIENT = mongomock.MongoClient()
_DB = _CLIENT["sandy_audit"]
appdb._db = _DB
appdb.get_db = lambda: _DB

register_all_tools()
registry = get_registry()

# One plausible argument set per tool, keyed by name. Anything absent is
# dispatched with {} — which is itself a test: a handler must survive being
# called with nothing.
ARGS = {
    "task_create": {"title": "مهمة اختبار"},
    "task_complete": {"title": "مهمة اختبار"},
    "task_delete": {"title": "مهمة اختبار"},
    "task_list": {},
    "task_update": {"title": "مهمة اختبار", "new_title": "معدّلة"},
    "reminder_create": {"title": "تذكير", "when": "بكرا الساعة عشرة"},
    "reminder_delete": {"title": "تذكير"},
    "reminder_list": {},
    "memory_store": {"content": "معلومة"},
    "memory_search": {"query": "معلومة"},
    "shopping_add": {"item": "حليب"},
    "habit_add": {"name": "مشي"},
    "expense_add": {"amount": 10, "category": "أكل"},
    "journal_add": {"content": "اليوم"},
    "book_add": {"title": "كتاب"},
    "goal_set": {"title": "هدف"},
    "device_control": {"device": "نور", "action": "on"},
    "scene_apply": {"scene": "نوم"},
    "image_generate": {"prompt": "قطة"},
    "web_search": {"query": "طقس"},
    "weather_now": {},
    "brainstorm_start": {"topic": "فكرة"},
}

state = {"chat_id": "audit-chat", "user_id": "audit-user", "message": "اختبار"}

profile = {"user_id": "audit-user", "chat_id": "audit-chat", "name": "Audit",
           "is_owner": True, "is_guest": False, "permissions": "all", "relation": "owner"}

results = []
names = sorted(registry.all_names())
for name in names:
    args = ARGS.get(name, {})
    session = {"_destructive_confirmed": True}
    ctx = DispatchContext(
        user_message="اختبار",
        normalized_message="اختبار",
        session=session,
        state=state,
        mongo_db=_DB,
        create_chat_completion_fn=None,
    )
    try:
        with user_profiles.active_user_profile_context(profile):
            out = ToolDispatcher().dispatch(name, args, ctx)
        reply = str(out.get("reply") or "")[:70].replace("\n", " ")
        if result_failed(out):
            status = "ERROR"          # the tool itself broke, friendly sentence or not
        elif not out.get("handled"):
            status = "NOT-HANDLED"    # a routing signal, not breakage
        elif not result_ok(out):
            status = "REFUSED"        # it ran; the answer is no
        else:
            status = "OK"
        results.append((name, status, reply))
    except Exception as exc:  # noqa: BLE001 — this probe exists to see them all
        results.append((name, "RAISED", f"{type(exc).__name__}: {exc}"))
        traceback.print_exc(limit=3)

print(f"\n{'=' * 100}")
print(f"{len(results)} tools dispatched")
print("=" * 100)
for name, status, reply in results:
    print(f"{status:12} | {name:32} | {reply}")

counts = {k: sum(1 for r in results if r[1] == k)
          for k in ("RAISED", "ERROR", "NOT-HANDLED", "REFUSED", "OK")}
print("\n" + "   ".join(f"{k}: {v}" for k, v in counts.items()))
# RAISED and ERROR are the two that mean something is broken. The others are a
# tool doing its job: declining to own the turn, or owning it and saying no.
if counts["RAISED"] or counts["ERROR"]:
    print(f"\n{counts['RAISED'] + counts['ERROR']} tool(s) are broken, "
          f"not merely refusing — see the lines above.")
