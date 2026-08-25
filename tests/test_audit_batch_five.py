"""Regressions for batch five: the project not following its own rules.

Two rules, both written down, both broken in the places that run most often.

`CONVENTIONS.md` C3 — fire-and-forget goes through `submit_background`, raw
`threading.Thread` is not allowed. Five sites used one, all per request: one per
turn that retrieved anything, one per photo, one per photo again, one per reply
that needed a title.

`ARCHITECTURE_MAP.md` §2.6 — never reintroduce a raw collection handle on a
request path, because one forgotten filter there is a cross-tenant leak. Six
memory modules did exactly that, stamping the tenant by hand, and
`test_tenant_scoping_guard.py` could not see any of them. They could not move
before this audit: they run on background threads, and the tenant lives in a
`ContextVar` that did not cross one until `submit_background` started carrying
it.

Plus three pieces of code that could not do anything at all.
"""
from __future__ import annotations

import ast
import pathlib
import time

import mongomock
import pytest


ROOT = pathlib.Path(__file__).resolve().parent.parent
CLOUD = ROOT / "cloud" / "app"

A = {"user_id": "tenant-a", "chat_id": "tenant-a", "relation": "user",
     "permissions": "all", "is_guest": False}
B = {"user_id": "tenant-b", "chat_id": "tenant-b", "relation": "user",
     "permissions": "all", "is_guest": False}


@pytest.fixture()
def db():
    import app.db as appdb

    database = mongomock.MongoClient()["t"]
    appdb.configure(database)
    try:
        yield database
    finally:
        appdb.reset()


def _drain():
    from app.utils.thread_pool import sandy_executor

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and sandy_executor._work_queue.qsize():
        time.sleep(0.02)
    time.sleep(0.3)


# ── C3: no raw threads for fire-and-forget ───────────────────────────────────

def test_fire_and_forget_work_uses_the_shared_pool():
    """Three shapes are exempt and each says so where it sits — a long-lived
    singleton, and work the request itself waits on (`CONVENTIONS.md` C3b).
    Everything else creates a thread per request, unbounded under load, and
    does it without carrying the tenant."""
    exempt = {
        "features/speaker_id.py",       # one-shot model warm-up
        "integrations/mqtt_ingest.py",  # the reconnect watchdog
        "api/server.py",                # /api/agent/stream — the request waits
    }
    offenders = []
    for path in sorted(CLOUD.rglob("*.py")):
        rel = str(path.relative_to(CLOUD))
        if rel in exempt:
            continue
        for node in ast.walk(ast.parse(path.read_text(), rel)):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "Thread"):
                offenders.append(f"{rel}:{node.lineno}")

    assert not offenders, f"raw threads against C3: {offenders}"


# ── §2.6: no raw collection handles in the memory layer ──────────────────────

WRITERS = ("emotional_ltm", "relationships_memory", "lessons_memory",
           "shared_history", "interests_tracker", "health_monitor")


@pytest.mark.parametrize("module", WRITERS)
def test_a_memory_module_goes_through_scoped(module):
    src = (CLOUD / "agent" / f"{module}.py").read_text()
    assert "scoped(" in src, f"{module} does not use the tenant wrapper"
    # The tenant is stamped by the wrapper, never by the caller — a caller that
    # writes its own cannot be prevented from writing somebody else's.
    assert '"chat_id": str(chat_id)' not in src

    # **Index creation is the one exception, and it is written down**
    # (`tenant_db.py`): it runs at boot, before any request has set a tenant, so
    # `scoped()` would return None and no index would ever be created — and
    # `ScopedCollection` has no `create_index` to call in the first place.
    raw_uses = [ln.strip() for ln in src.splitlines() if "mongo_db[_COLL]" in ln]
    for line in raw_uses:
        assert "coll = mongo_db[_COLL]" == line, f"{module}: raw handle at {line!r}"
    if raw_uses:
        assert "def ensure_ttl_index" in src, \
            f"{module} holds a raw handle outside index creation"


def test_the_memory_writers_actually_write(db):
    """**"It did not raise" proves nothing here.**

    `scoped()` returns None with no tenant and every store guards
    `if coll is None: return`, so the failure mode is silence: no exception, no
    log line, and Sandy simply stops remembering. These run on background
    threads, which is exactly where the tenant used not to reach.

    Driven through `graph._save_emotional_async`, the production path.
    """
    from app.agent.graph.graph import _save_emotional_async
    from app.utils import user_profiles

    msg = ("زهقت من الشغل، أخوي محمد قاللي اهدى، وتعلمت إني لازم أرتاح، "
           "وذكرى تخرجي بكرا، بحب البرمجة")
    with user_profiles.active_user_profile_context(A):
        _save_emotional_async(
            {"mood": "stressed", "chat_id": "tenant-a", "user_id": "tenant-a"}, msg)
    _drain()

    docs = list(db["sandy_memories"].find({}))
    assert docs, "nothing was written — the tenant did not reach the pool thread"
    assert db["sandy_activity"].count_documents({}) > 0
    for doc in docs:
        assert doc.get("chat_id") == "tenant-a", \
            "a document was written without the tenant the wrapper should stamp"


def test_one_tenant_cannot_read_another_ones_memories(db):
    from app.agent.emotional_ltm import get_emotional_context, save_emotional_moment
    from app.agent.relationships_memory import (
        get_relationships_context, save_relationship,
    )
    from app.utils import user_profiles

    with user_profiles.active_user_profile_context(A):
        save_emotional_moment("stressed", "مشروع الشغل")
        save_relationship("أخوي", "محمد")
    with user_profiles.active_user_profile_context(B):
        seen = (str(get_emotional_context() or "")
                + str(get_relationships_context() or ""))

    assert "مشروع الشغل" not in seen
    assert "محمد" not in seen


def test_the_memory_layer_fails_closed_without_a_tenant(db):
    """`scoped()` returns None with no active tenant, so an unauthenticated
    context reads nothing and writes nothing — which is what makes the hand-
    stamped filters safe to delete."""
    from app.agent.emotional_ltm import get_emotional_context
    from app.agent.lessons_memory import save_lesson
    from app.utils import user_profiles

    with user_profiles.active_user_profile_context(None):
        save_lesson("درس من العدم")
        assert get_emotional_context() is None

    assert db["sandy_memories"].count_documents({}) == 0


# ── Code that could not do anything ──────────────────────────────────────────

def test_the_chat_fallback_does_not_read_a_dict_it_just_emptied():
    """`session: Dict[str, Any] = {}` then `session.get("pending_action")` two
    lines later. Always None — that branch calls the model and nothing else, so
    no handler ever writes a pending there."""
    src = (CLOUD / "agent/nodes/execute.py").read_text()
    body = src[src.index("def execute_node"):]
    assert "session: Dict[str, Any] = {}" not in body
    assert "def _noop_save(" not in src, "_noop_save is defined and never used"


def test_replies_are_not_chunked_for_a_transport_that_was_removed():
    """`get_final_reply` split at 4096 — Telegram's message limit — and
    `server.py` rejoined the pieces with a newline on the next line. Pure loss:
    it cuts at a space or a newline and puts a newline back, so a long reply
    could gain a break in the middle of a sentence."""
    graph = (CLOUD / "agent/graph/graph.py").read_text()
    server = (CLOUD / "api/server.py").read_text()
    assert "_TG_LIMIT" not in graph
    assert 'reply.get("chunks")' not in server


def test_the_map_does_not_contradict_itself_about_the_camera():
    """§5 said in bold that `vision-core/` does not exist while §4.6 said it was
    flashed and answering on the broker. A map that lies is worse than no map."""
    mp = (ROOT / "ARCHITECTURE_MAP.md").read_text()
    assert (ROOT / "vision-core").exists()
    assert "**this directory does not exist.**" not in mp


def test_index_creation_stays_on_the_raw_handle(db):
    """`ensure_ttl_index` runs at boot with no tenant. Converting it to
    `scoped()` — which the script that moved these modules did — means
    `scoped()` returns None and `sandy_activity` gets no TTL and no
    `(chat_id, created_at)` index, on a fresh deployment, silently: `bootstrap`
    catches the failure and logs it at warning."""
    from app.agent.health_monitor import ensure_ttl_index
    from app.utils import user_profiles

    with user_profiles.active_user_profile_context(None):
        ensure_ttl_index(db)

    names = set(db["sandy_activity"].index_information())
    assert len(names) > 1, "no index was created at boot"


def test_the_chat_fallback_still_clears_a_stale_pending(db, monkeypatch):
    """**The read was dead; the write was not.**

    `session.get("pending_action")` on a dict created empty two lines above did
    always return `None` — but that `None` was *written* into `pending_state`,
    which cleared whatever was there, and `server.py` persists `pending_state`
    on the next line. Delete the read and the clear goes with it: a pending from
    an earlier turn survives a fallback turn and an "أوكي" fifteen minutes later
    fires it. Commit `912035a` exists because of exactly that.
    """
    import app.agent.nodes.execute as ex
    from app.agent.pending import create_pending_action
    from app.utils import user_profiles

    monkeypatch.setattr(ex, "_get_chat_completion_fn", lambda: (lambda **kw: None))
    monkeypatch.setattr(ex, "_handle_chat", lambda *a, **kw: "أهلين")

    stale = create_pending_action(
        {"type": "task", "action": "delete", "task_text": "مهمة قديمة"})
    with user_profiles.active_user_profile_context(A):
        out = ex.execute_node({
            # A non-chat intent with no function call — the branch that used
            # to build `updates` with the `pending_state` clear in it. A chat
            # intent returns earlier, from a branch this change never touched.
            "chat_id": "tenant-a", "user_id": "tenant-a", "message": "ضيف مهمة",
            "intent": "task.create", "pending_state": stale,
        })

    assert out.get("pending_state") is None, \
        "a stale confirmation survived a turn that never touched it"
