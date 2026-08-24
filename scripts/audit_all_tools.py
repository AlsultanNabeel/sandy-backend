"""Exercise every registered tool against a mongomock database.

Not a pytest file on purpose (see pytest.ini): it is a manual probe. Run it as
``python3 scripts/audit_all_tools.py`` from the repo root. For each tool it
dispatches a plausible argument set, records whether the call raised, and prints
one line per tool so a broken handler is visible by name rather than by symptom.
"""
from __future__ import annotations

import os
import sys
import traceback

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_ROOT, os.path.join(_ROOT, "cloud")]

import mongomock  # noqa: E402

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
        results.append((name, "handled" if out.get("handled") else "NOT-HANDLED", reply))
    except Exception as exc:  # noqa: BLE001 — this probe exists to see them all
        results.append((name, "RAISED", f"{type(exc).__name__}: {exc}"))
        traceback.print_exc(limit=3)

print(f"\n{'=' * 100}")
print(f"{len(results)} tools dispatched")
print("=" * 100)
for name, status, reply in results:
    print(f"{status:12} | {name:32} | {reply}")

raised = [r for r in results if r[1] == "RAISED"]
unhandled = [r for r in results if r[1] == "NOT-HANDLED"]
print(f"\nRAISED: {len(raised)}   NOT-HANDLED: {len(unhandled)}   OK: {len(results) - len(raised) - len(unhandled)}")
