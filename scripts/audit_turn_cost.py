"""Count what one chat turn actually costs, before any of it reaches a network.

Wraps the mongomock collection API so every find / find_one / count_documents /
aggregate / update is recorded with the collection it hit, and stubs the model
and embedding calls so the count is the *shape* of the turn rather than a
measurement of Azure's weather. Run from the repo root:

    python3 scripts/audit_turn_cost.py

The number that matters is round trips per message: every one of them is a
network hop to Atlas from Heroku, and they are serial unless someone made them
otherwise.
"""
from __future__ import annotations

import collections
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_ROOT, os.path.join(_ROOT, "cloud")]

import mongomock  # noqa: E402

os.environ.setdefault("JWT_SECRET", "audit-secret")

OPS: collections.Counter = collections.Counter()
CALLS: collections.Counter = collections.Counter()

_WATCHED = ("find", "find_one", "count_documents", "aggregate", "update_one",
            "update_many", "insert_one", "delete_one", "delete_many",
            "find_one_and_update", "distinct", "create_index")


class _CountingCollection:
    def __init__(self, inner, name):
        self._inner = inner
        self._name = name

    def __getattr__(self, item):
        attr = getattr(self._inner, item)
        if item in _WATCHED and callable(attr):
            def _wrapped(*a, **kw):
                OPS[f"{self._name}.{item}"] += 1
                return attr(*a, **kw)
            return _wrapped
        return attr


class _CountingDB:
    def __init__(self, inner):
        self._inner = inner

    def __getitem__(self, name):
        return _CountingCollection(self._inner[name], name)

    def __getattr__(self, item):
        if item.startswith("_"):
            return getattr(self._inner, item)
        return _CountingCollection(self._inner[item], item)


_CLIENT = mongomock.MongoClient()
_DB = _CountingDB(_CLIENT["sandy_audit"])

import app.db as appdb  # noqa: E402
appdb.configure(_DB)

# Stub the outside world so the count reflects call *sites*, not latency.
import app.agent.semantic_memory as sem  # noqa: E402


def _fake_embed(text):
    CALLS["embedding_api_call"] += 1
    return [0.01] * 8


sem._embed = _fake_embed

class _FakeMsg:
    tool_calls = None
    content = "تمام"


def _fake_complete(self, system, user, tools, **kw):
    CALLS["router_llm_call"] += 1
    CALLS["router_tools_sent"] = len(tools)
    CALLS["router_prompt_chars"] = len(system) + len(user)
    return _FakeMsg()


from app.integrations.azure_intent_client import AzureIntentClient  # noqa: E402
AzureIntentClient.complete_with_tools = _fake_complete
AzureIntentClient.__init__ = lambda self, *a, **kw: None

import app.agent.nodes.execute as ex  # noqa: E402


def _fake_chat_fn():
    def _fn(messages, **kw):
        CALLS["chat_llm_call"] += 1

        class _C:
            class message:  # noqa: N801
                content = "تمام يا صديقي"
        class _R:
            choices = [_C]
        return _R()
    return _fn


ex._get_chat_completion_fn = _fake_chat_fn

from app.agent.tools.setup import register_all_tools  # noqa: E402
from app.agent.graph.graph import run_graph  # noqa: E402
from app.utils.user_profiles import active_user_profile_context  # noqa: E402

register_all_tools()

USER = "audit-user"
PROFILE = {"user_id": USER, "chat_id": USER, "name": "Audit", "relation": "owner",
           "permissions": "all", "tone": "casual"}

# Seed a realistic life: the cost of a turn scales with what the person owns.
raw = _CLIENT["sandy_audit"]
for i in range(30):
    raw["sandy_tasks"].insert_one({"user_id": USER, "text": f"مهمة {i}", "done": False})
for i in range(20):
    raw["sandy_reminders"].insert_one({"user_id": USER, "text": f"تذكير {i}"})
for i in range(10):
    raw["sandy_habits"].insert_one({"user_id": USER, "name": f"عادة {i}"})
for i in range(15):
    raw["sandy_books"].insert_one({"user_id": USER, "title": f"كتاب {i}", "status": "reading"})
for i in range(40):
    raw["sandy_journal"].insert_one({"user_id": USER, "text": f"يومية {i}", "date": "2026-08-01"})
for i in range(10):
    raw["sandy_shopping"].insert_one({"user_id": USER, "item": f"غرض {i}", "done": False})

seeded = sum(raw[c].count_documents({}) for c in
             ("sandy_tasks", "sandy_reminders", "sandy_habits", "sandy_books",
              "sandy_journal", "sandy_shopping"))

OPS.clear()
CALLS.clear()

with active_user_profile_context(PROFILE):
    state = run_graph("مرحبا كيفك اليوم", user_id=USER, chat_id=USER, source="web")

# **Wait for the background pool to drain, do not sleep for a guess.**
#
# Background work is fired onto `sandy_executor`, and a fixed sleep made the
# total depend on how fast the machine happened to be that minute: the same tree
# measured 40 one hour and 42 the next, which is worse than useless for a number
# whose whole job is to be compared against a later reading. Draining is exact.
import time  # noqa: E402
from app.utils.thread_pool import sandy_executor  # noqa: E402

# `qsize() == 0` means the last job was *dequeued*, not that it finished, so the
# quiet period below is still part of the condition — it is a bound on how long
# a job may keep writing after being picked up, not a guess at total duration.
# This drains `sandy_executor` only; `_SOUL_POOL` jobs the request abandoned may
# still be running, and their writes land after this print.
_deadline = time.monotonic() + 30.0
while time.monotonic() < _deadline:
    if sandy_executor._work_queue.qsize() == 0:
        time.sleep(0.25)
        if sandy_executor._work_queue.qsize() == 0:
            break
    time.sleep(0.05)
else:
    print("WARNING: background pool did not drain in 30s — total is a lower bound")

print(f"\nSeeded life items: {seeded}")
print(f"Reply: {state.get('final_response')!r}\n")
print("=" * 74)
print("MONGO ROUND TRIPS FOR ONE CHAT TURN")
print("=" * 74)
total = 0
for op, n in OPS.most_common():
    print(f"{n:5}  {op}")
    total += n
print("-" * 74)
print(f"{total:5}  TOTAL round trips")
print()
print("=" * 74)
print("EXTERNAL CALLS")
print("=" * 74)
for k, v in CALLS.most_common():
    print(f"{v:7}  {k}")
