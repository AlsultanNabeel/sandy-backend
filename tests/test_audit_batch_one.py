"""Regressions from the 24 Aug 2026 audit, batch one.

Each test here failed before its fix and names the symptom the owner saw, so a
future change that reintroduces one of them fails with a sentence rather than a
stack trace.
"""
from __future__ import annotations

import mongomock
import pytest


# ── 2. A new user is not a stranger ──────────────────────────────────────────
#
# A customer who had just finished first-run setup, with nothing else saved,
# got nothing back and Sandy asked who they were.

@pytest.fixture
def fresh_customer():
    """A customer who has finished onboarding and owns one fact."""
    import app.db as appdb
    from app.blocks import entries

    db = mongomock.MongoClient()["t"]
    appdb.configure(db)
    uid = "fresh-user"
    db["sandy_users"].insert_one({
        "_id": uid,
        "onboarding": {"preferred_name": "سامي", "interests": ["تصوير"]},
    })
    from app.utils.user_profiles import active_user_profile_context
    with active_user_profile_context({"chat_id": uid}):
        entries.add("fact", "عنده جواز لازم يطلعه", embed=False)
    try:
        yield uid, db
    finally:
        appdb.reset()


def test_chat_path_knows_a_fresh_customer(fresh_customer):
    from app.brain import context
    from app.utils.user_profiles import active_user_profile_context

    uid, _db = fresh_customer
    with active_user_profile_context({"chat_id": uid}):
        text = context.build_system(uid, "مرحبا")
    assert "سامي" in text, "his name comes from onboarding"
    assert "جواز" in text, "his facts come from the log"


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
    assert "جواز" in text, "her memory seed had none of his life in it"


# ── 3. The indexes the hot reads need ────────────────────────────────────────

def test_stm_has_the_index_recent_turns_for_user_needs():
    """`recent_turns_for_user` filters user_id and sorts updated_at, on every
    chat turn and twice per voice session. Without this it scanned every
    conversation on the server."""
    import app.db as appdb
    from app.brain import stm
    from app.brain.stm import _stm_collection

    db = mongomock.MongoClient()["t"]
    appdb.configure(db)
    stm._stm_index_ready = False
    try:
        _stm_collection()
        keys = [tuple(i["key"].items()) for i in db["sandy_stm"].list_indexes()]
        assert (("user_id", 1), ("updated_at", -1)) in keys
    finally:
        stm._stm_index_ready = False
        appdb.reset()


def test_stm_indexes_are_created_independently():
    """One index failing must not take the ones after it down with it.

    They shared a single `try`, and the ready-flag was set regardless — so a TTL
    conflict (which is what changing STM_TTL produces) silently cost the
    compound index for the life of the process.
    """
    import app.db as appdb
    from app.brain import stm

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
        stm._ensure_stm_indexes(_Sabotaged(db["sandy_stm"]))
        keys = [tuple(i["key"].items()) for i in db["sandy_stm"].list_indexes()]
        assert (("user_id", 1), ("updated_at", -1)) in keys, \
            "a failed TTL index must not skip the index every chat turn needs"
        assert (("key", 1),) in keys
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
    monkeypatch.setattr(sess, "_build_cached_instruction",
                        lambda *a: (_ for _ in ()).throw(RuntimeError("mongo down")))
    monkeypatch.setattr(sess, "resolve_speaker_label", lambda who: "سامي")
    monkeypatch.setattr(sess, "load_recent_turns", lambda who: [])
    monkeypatch.setattr(sess, "speaker_gate", lambda who, channel: False)
    monkeypatch.setattr(sess, "voice_seconds_left", lambda who: 3600.0)
    monkeypatch.setattr(sess, "_send_json", lambda ws, payload: None)

    pytest.importorskip("google.genai")
    monkeypatch.setattr("app.config.GEMINI_API_KEY", "test-key", raising=False)

    class _WS:
        environ: dict = {}

        def send(self, _):
            pass

    # A paired board: one nobody paired is turned away before the reader starts.
    sess.set_voice_identity("u1")
    try:
        asyncio.run(sess._live_session(_WS(), "test"))
    finally:
        sess.set_voice_identity("")
    assert stopped["n"] == 1, "a session that fails during setup must stop its reader"


# ── 6. A quota rejection is a sentence, not a code ───────────────────────────

def test_a_quota_rejection_is_a_sentence_not_a_code(monkeypatch):
    """The app shows what the server puts in `message`; sending only the machine
    code told an Arabic-speaking user "daily_quota_exceeded".

    Driven through the real route so it covers the wiring, not just the table:
    a free-tier user is pushed past the per-minute limit and the 429 body is
    read back.
    """
    import app.db as appdb
    from app.api.server import create_app

    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setattr("app.brain.loop.run_turn", lambda message, **kw: {"final_response": "هلا"})
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
