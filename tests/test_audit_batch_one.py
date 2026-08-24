"""Regressions for the five defects fixed in the 24 Aug 2026 audit, batch one.

Each test here failed before its fix and names the symptom the owner saw, so a
future change that reintroduces one of them fails with a sentence rather than a
stack trace.
"""
from __future__ import annotations

import logging

import mongomock
import pytest


# ── 1. Telemetry must never fail a turn ──────────────────────────────────────
#
# `_log_azure_usage` ran `logger.info(..., flush=True)`. `Logger.info` takes no
# such keyword, so it raised TypeError *after* a successful model call;
# `route_with_fc` read that as a routing failure and dropped to the two-intent
# fallback, so every tool except tasks and reminders became plain chat.
#
# The branch only runs on a prompt-cache hit — which is the normal case, since
# the tool catalogue is a stable ~9k-token prefix built to be cached. So message
# one of a session worked and every message after it did not.
#
# It hid from the suite because `Logger.info` returns before `_log` when INFO is
# disabled, and the suite runs at WARNING. Hence `caplog.set_level(INFO)`: that
# is not decoration, it is the whole point of the test.

class _FakeDetails:
    cached_tokens = 512


class _FakeUsage:
    prompt_tokens = 2000
    completion_tokens = 20
    prompt_tokens_details = _FakeDetails()


class _FakeUsageNoCache:
    prompt_tokens = 2000
    completion_tokens = 20
    prompt_tokens_details = None


class _FakeResponse:
    def __init__(self, usage):
        self.usage = usage


@pytest.mark.parametrize("usage", [_FakeUsage(), _FakeUsageNoCache()])
def test_usage_logging_emits_its_line(caplog, usage):
    """**Asserts the line was emitted, not merely that nothing escaped.**

    The fix also wrapped the body in a guard, and a guard swallows `TypeError` —
    which is what `flush=True` raised. So "did not raise" is a property the
    guard grants unconditionally, and a test asserting only that would pass with
    the bug fully present. What distinguishes fixed from broken-and-swallowed is
    whether the record actually reached the log.
    """
    from app.integrations.azure_intent_client import _log_azure_usage

    caplog.set_level(logging.INFO)
    _log_azure_usage(_FakeResponse(usage))
    assert any("[Azure] in=" in r.getMessage() for r in caplog.records), \
        "the usage line was swallowed — the log call itself is failing"


def test_usage_logging_survives_a_broken_response(caplog):
    """A nonsense usage object costs a warning, not the turn.

    Also pins the reporting level: the original bug survived because production
    runs at INFO and nothing below it is visible there, so the guard that
    replaced it must not report at DEBUG.
    """
    from app.integrations.azure_intent_client import _log_azure_usage

    class _Bad:
        # A string where a count belongs: `in_tok - cached` raises TypeError.
        # (A property that raises would not do — `getattr(..., None)` swallows
        # AttributeError, so that path degrades on its own and never reaches
        # the guard.)
        prompt_tokens = "not a number"
        completion_tokens = 5
        prompt_tokens_details = None

    caplog.set_level(logging.INFO)
    _log_azure_usage(_FakeResponse(_Bad()))
    skipped = [r for r in caplog.records if "usage log skipped" in r.getMessage()]
    assert skipped, "a telemetry failure must still say so"
    assert skipped[0].levelno >= logging.WARNING, \
        "reporting below WARNING is how the original bug stayed hidden"


def test_usage_logging_ignores_a_response_with_no_usage(caplog):
    from app.integrations.azure_intent_client import _log_azure_usage

    caplog.set_level(logging.INFO)
    _log_azure_usage(_FakeResponse(None))
    assert not [r for r in caplog.records if "[Azure]" in r.getMessage()]


def test_memory_index_logging_never_raises(caplog):
    """Same `flush=True` mistake, copied into semantic_memory twice.

    The log line only runs when something was actually inserted, so this needs a
    tenant profile — without one `scoped()` returns None, nothing is written,
    and the test would pass by never reaching the line it exists to guard.
    """
    import app.agent.semantic_memory as sem
    import app.db as appdb
    from app.utils.user_profiles import active_user_profile_context

    db = mongomock.MongoClient()["t"]
    appdb.configure(db)
    profile = {"user_id": "log-user", "chat_id": "log-user",
               "permissions": "all", "relation": "owner"}
    caplog.set_level(logging.INFO)
    try:
        with active_user_profile_context(profile):
            sem.load_facts_to_chroma([{"text": "حقيقة", "type": "general"}])
            sem.load_conversations_to_chroma([{"user": "مرحبا", "sandy": "أهلين"}])
        assert db["sandy_facts"].count_documents({}) == 1, \
            "nothing was written, so the log line under test never ran"
        assert db["sandy_conversations"].count_documents({}) == 1
    finally:
        appdb.reset()


# ── 2. A new user is not a stranger ──────────────────────────────────────────
#
# `get_persona_directives` returned None when `sandy_memories` was empty, which
# also threw away the life snapshot, the life search and the onboarding profile
# — none of which come from that collection. A customer who had just finished
# first-run setup got nothing back and Sandy asked who they were.

@pytest.fixture
def fresh_customer():
    """A customer who has finished onboarding and owns a few things, and has
    never had a single document written to `sandy_memories`."""
    import app.db as appdb

    db = mongomock.MongoClient()["t"]
    appdb.configure(db)
    uid = "fresh-user"
    db["sandy_users"].insert_one({
        "_id": uid,
        "onboarding": {"preferred_name": "سامي", "interests": ["تصوير"]},
    })
    db["sandy_tasks"].insert_one({"user_id": uid, "text": "أطلع الجواز", "done": False})
    db["sandy_books"].insert_one({"user_id": uid, "title": "العادات الذرية",
                                  "status": "reading"})
    assert db["sandy_memories"].count_documents({}) == 0
    try:
        yield uid, db
    finally:
        appdb.reset()


def test_chat_path_knows_a_fresh_customer(fresh_customer):
    """**Goes through the soul pool, because that is where it broke.**

    Two defects stacked here and either one alone made her a stranger:
    `get_persona_directives` returned None when `sandy_memories` was empty, and
    the pool submit dropped the tenant profile so every `scoped()` read inside
    came back empty anyway. Calling the function directly inside a profile —
    the obvious way to write this test — is the one arrangement where both are
    invisible.
    """
    from app.agent.context_builder import get_persona_directives
    from app.agent.nodes.soul import _submit
    from app.utils.user_profiles import active_user_profile_context

    uid, db = fresh_customer
    profile = {"user_id": uid, "chat_id": uid, "permissions": "all",
               "relation": "owner"}

    with active_user_profile_context(profile):
        out = _submit(get_persona_directives, uid, uid, db,
                      message="شو كتبي").result(timeout=10)

    assert out, "a customer with tasks and an onboarding profile is not empty"
    assert "سامي" in out, "his name comes from onboarding, not from sandy_memories"
    assert "أطلع الجواز" in out, "the life snapshot is read through scoped() stores"
    assert "العادات الذرية" in out, "the life search needs `message` to be passed on"


def test_voice_path_knows_a_fresh_customer(fresh_customer):
    """The same two defects, reached through the voice session's instruction
    build — which runs on a pool thread with no ambient profile at all."""
    import app.api.voice_ws.tools as vt
    from app.api.voice_ws.memory import set_voice_identity

    uid, _db = fresh_customer
    set_voice_identity("")            # a pool thread starts blank
    try:
        text = vt._build_system_instruction(uid)
    finally:
        set_voice_identity("")

    assert "سامي" in text, "the robot greeted its owner as a stranger"
    assert "أطلع الجواز" in text, "her memory seed had none of his life in it"


# ── 3. The indexes the hot reads need ────────────────────────────────────────

def test_stm_has_the_index_recent_turns_for_user_needs():
    """`recent_turns_for_user` filters user_id and sorts updated_at, on every
    chat turn and twice per voice session. Without this it scanned every
    conversation on the server."""
    import app.db as appdb
    from app.agent.graph.graph import _stm_collection
    import app.agent.graph.graph as graph_mod

    db = mongomock.MongoClient()["t"]
    appdb.configure(db)
    graph_mod._stm_index_ready = False
    try:
        _stm_collection()
        keys = [tuple(i["key"].items()) for i in db["sandy_stm"].list_indexes()]
        assert (("user_id", 1), ("updated_at", -1)) in keys
    finally:
        graph_mod._stm_index_ready = False
        appdb.reset()


def test_stm_indexes_are_created_independently():
    """One index failing must not take the ones after it down with it.

    They shared a single `try`, and the ready-flag was set regardless — so a TTL
    conflict (which is what changing STM_TTL produces) silently cost the
    compound index for the life of the process.
    """
    import app.db as appdb
    import app.agent.graph.graph as graph_mod

    db = mongomock.MongoClient()["t"]
    appdb.configure(db)

    class _Sabotaged:
        """Fails on the TTL index the way a live options-conflict would."""

        def __init__(self, real):
            self._real = real

        def create_index(self, keys, **kw):
            if "expireAfterSeconds" in kw:
                raise RuntimeError("IndexOptionsConflict")
            return self._real.create_index(keys, **kw)

    try:
        graph_mod._ensure_stm_indexes(_Sabotaged(db["sandy_stm"]))
        keys = [tuple(i["key"].items()) for i in db["sandy_stm"].list_indexes()]
        assert (("user_id", 1), ("updated_at", -1)) in keys, \
            "a failed TTL index must not skip the index every chat turn needs"
        assert (("key", 1),) in keys
    finally:
        appdb.reset()


def test_bootstrap_creates_the_sandy_memories_index():
    """`sandy_memories` grows forever and had no index at all; both of its hot
    readers scanned the whole collection on every message."""
    import app.db as appdb
    from app import bootstrap

    db = mongomock.MongoClient()["t"]
    appdb.configure(db)
    try:
        bootstrap.ensure_indexes()
        keys = [tuple(i["key"].items()) for i in db["sandy_memories"].list_indexes()]
        assert (("chat_id", 1), ("label", 1), ("created_at", -1)) in keys
    finally:
        appdb.reset()


# ── 4. A failed voice session gives its thread back ──────────────────────────

def test_live_session_stops_the_reader_when_setup_fails(monkeypatch):
    """The reader owns a thread and an executor from `start()`. The finally that
    released them used to begin below the config checks, so every failed
    connection attempt leaked one of each — and a robot retries."""
    import asyncio

    from app.api.voice_ws import session as sess

    stopped = {"n": 0}

    class _FakeReader:
        dropped = 0

        def start(self):
            return self

        def stop(self):
            stopped["n"] += 1

    monkeypatch.setattr(sess, "_DeviceReader", lambda ws: _FakeReader())
    monkeypatch.setattr(sess, "_build_system_instruction",
                        lambda who: (_ for _ in ()).throw(RuntimeError("mongo down")))
    monkeypatch.setattr(sess, "_send_json", lambda ws, payload: None)

    pytest.importorskip("google.genai")
    monkeypatch.setattr("app.config.GEMINI_API_KEY", "test-key", raising=False)

    class _WS:
        environ: dict = {}

        def send(self, _):
            pass

    asyncio.run(sess._live_session(_WS(), "test"))
    assert stopped["n"] == 1, "a session that fails during setup must stop its reader"


# ── 5. Semantic summary recall asks for the field it reads ───────────────────

def test_summary_vector_search_projects_the_summary_field(monkeypatch):
    """`_vector_search` only returns the fields it is asked to project, and this
    caller asked for none of them, then read `summary`. Every hit was dropped."""
    import app.agent.semantic_memory as sem
    import app.db as appdb

    db = mongomock.MongoClient()["t"]
    appdb.configure(db)
    captured = {}

    def _fake_vector_search(col, query, chat_id, n_results, extra_project):
        captured["projected"] = dict(extra_project)
        # What Atlas would hand back, honouring the projection it was given.
        doc = {"summary": "حكينا عن السفر"}
        return [{k: v for k, v in doc.items() if k in extra_project}]

    monkeypatch.setattr(sem, "_vector_search", _fake_vector_search)
    try:
        out = sem.search_relevant_summaries("سفر", "chat-1")
        assert "summary" in captured["projected"], \
            "the caller must project the field it then reads"
        assert out == ["حكينا عن السفر"], \
            "a matched summary was found and then silently discarded"
    finally:
        appdb.reset()


# ── 6. A quota rejection is a sentence, not a code ───────────────────────────

def test_a_quota_rejection_is_a_sentence_not_a_code():
    """The app shows what the server puts in `message`; sending only the machine
    code told an Arabic-speaking user "daily_quota_exceeded".

    Driven through the real route so it covers the wiring, not just the table:
    a free-tier user is pushed past the per-minute limit and the 429 body is
    read back.
    """
    import app.db as appdb
    from app.api.server import create_app

    db = mongomock.MongoClient()["t"]
    appdb.configure(db)
    try:
        app = create_app(mongo_db=db)
        from app.api.auth_handlers import make_token

        token = make_token(user_id="quota-user", role="user")
        client = app.test_client()
        headers = {"Authorization": f"Bearer {token}"}

        body = None
        for _ in range(40):
            resp = client.post("/api/agent", json={"message": "مرحبا"},
                               headers=headers)
            if resp.status_code == 429:
                body = resp.get_json()
                break
        assert body is not None, "the per-minute limit never tripped"
        assert body.get("error"), "the machine code is what the app branches on"
        assert body.get("message"), "and the sentence is what it shows the user"
        assert body["message"] != body["error"], \
            "showing the code as the explanation is the bug this guards"
        assert not body["message"].isascii(), \
            "an Arabic-speaking user gets an Arabic sentence"
    finally:
        appdb.reset()
