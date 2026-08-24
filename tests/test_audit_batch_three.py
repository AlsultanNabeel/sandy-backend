"""Regressions for batch three of the 24 Aug 2026 audit: what a turn costs.

Measured, not guessed. With facts and summaries present — which the older probe
never seeded, so the semantic layer had been switched off in every reading — one
chat turn made the user wait for 49 database round trips and embedded the *same
query string twice*, once inside each of the two searches.

Three things are pinned here:

* one embedding per turn, not two;
* the ranking write that used to sit on the request path stays off it;
* the deadline on the soul pool is one policy, and giving up is reported.

The persona cache that this batch also tried is **not** here, deliberately. It
saved 26 of those round trips and was cut before commit: its premise was that
`ScopedCollection` is the single choke point for tenant writes, and
`users_store` and `memory_api` write on raw handles, so the two collections the
cache is built from would never have invalidated it.
"""
from __future__ import annotations

import mongomock
import pytest


OWNER = {"user_id": "o1", "chat_id": "o1", "name": "O", "is_owner": True,
         "is_guest": False, "permissions": "all", "relation": "owner"}


@pytest.fixture()
def db():
    import app.db as appdb

    database = mongomock.MongoClient()["t"]
    appdb.configure(database)
    try:
        yield database
    finally:
        appdb.reset()


def test_one_query_is_embedded_once_not_once_per_search(db, monkeypatch):
    """`search_relevant_summaries` and `search_relevant_facts` each called
    `_embed(query)` on the same string — two OpenAI round trips per message, on
    every channel, for one query."""
    import app.agent.semantic_memory as sem
    from app.utils import user_profiles

    calls = []
    monkeypatch.setattr(sem, "_embed", lambda text: (calls.append(text), [0.1] * 8)[1])
    monkeypatch.setattr(sem, "_vector_search",
                        lambda *a, **kw: [{"text": "حقيقة", "_id": 1},
                                          {"summary": "ملخص", "_id": 2}])

    db["sandy_facts"].insert_one({"chat_id": "o1", "text": "حقيقة"})
    with user_profiles.active_user_profile_context(OWNER):
        out = sem.search_memory_for_turn("وين وصلت بالكتاب", "o1")

    assert calls == ["وين وصلت بالكتاب"], \
        f"the query was embedded {len(calls)} times for one turn"
    assert set(out) == {"summaries", "facts"}


def test_a_search_still_works_when_the_embedding_fails(db, monkeypatch):
    """One embedding for two searches must not make one failure lose both.

    `_embed` returning None is the ordinary no-key / degraded case, and the
    keyword fallback underneath is what keeps recall working at all.
    """
    import app.agent.semantic_memory as sem
    from app.utils import user_profiles

    monkeypatch.setattr(sem, "_embed", lambda text: None)
    db["sandy_facts"].insert_one(
        {"chat_id": "o1", "text": "بقرا كتاب العادات", "usage_count": 0})

    with user_profiles.active_user_profile_context(OWNER):
        out = sem.search_memory_for_turn("العادات", "o1")

    assert out["facts"], "the keyword fallback did not run when embedding failed"


def test_the_ranking_write_is_not_on_the_request_path(db, monkeypatch):
    """`search_relevant_facts` did one `update_one` per result, inline, to bump a
    counter that changes nothing about this reply or the next one."""
    import threading

    import app.agent.semantic_memory as sem
    from app.utils import user_profiles

    for i in range(3):
        db["sandy_facts"].insert_one(
            {"chat_id": "o1", "text": f"حقيقة {i}", "usage_count": 0})

    seen_threads = []
    original = mongomock.collection.Collection.update_one

    def _spy(self, *a, **kw):
        if self.name == "sandy_facts":
            seen_threads.append(threading.current_thread().name)
        return original(self, *a, **kw)

    monkeypatch.setattr(mongomock.collection.Collection, "update_one", _spy)
    monkeypatch.setattr(sem, "_embed", lambda text: None)

    caller = threading.current_thread().name
    with user_profiles.active_user_profile_context(OWNER):
        sem.search_relevant_facts("حقيقة")

    assert caller not in seen_threads, \
        "the usage bump is still being written on the thread the user waits on"

    # And it must still happen — moving it must not mean losing it.
    from app.utils.thread_pool import sandy_executor

    sandy_executor.shutdown(wait=True)
    import app.utils.thread_pool as tp
    from concurrent.futures import ThreadPoolExecutor
    tp.sandy_executor = ThreadPoolExecutor(
        max_workers=10, thread_name_prefix="SandyWorker")

    assert db["sandy_facts"].count_documents({"usage_count": 1}) > 0, \
        "the ranking update was dropped rather than deferred"


def test_giving_up_on_a_soul_job_is_reported(caplog):
    """**A user who is suddenly a stranger is worth a warning.**

    `directives` is the entire persona — life snapshot, life search, onboarding
    line, preferences, relationships, lessons — and `soul_node` drops all of it
    on a `None`. Two of the four collection sites used to wait forever, which
    parked a gunicorn thread until the 120s kill; the other two gave up at three
    seconds and said nothing. One policy now, and it speaks.
    """
    import logging
    from concurrent.futures import Future

    import app.agent.nodes.soul as soul

    never = Future()  # never completes
    caplog.set_level(logging.WARNING)
    monkey = soul._SOUL_WAIT_S
    try:
        soul._SOUL_WAIT_S = 0.05
        assert soul._collect("directives", never) is None
    finally:
        soul._SOUL_WAIT_S = monkey
        never.cancel()

    assert any("directives" in r.message and "gave up" in r.message
               for r in caplog.records), \
        "a dropped persona left no trace above INFO"


def test_the_tls_fallback_that_accepted_any_certificate_is_gone():
    """Any failure of the first connect — including an interception — used to
    retry with `tlsAllowInvalidCertificates=True`, leaving one warning behind.
    Every message, memory and voiceprint then travelled over it."""
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent
           / "cloud/app/integrations/mongodb_store.py").read_text(encoding="utf-8")
    body = src.split("def init_mongo_connection")[1]
    # Comments stripped: the deletion is explained in one, and an assertion that
    # trips over its own explanation teaches the next reader to delete the note.
    code = "\n".join(ln for ln in body.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "tlsAllowInvalidCertificates" not in code
