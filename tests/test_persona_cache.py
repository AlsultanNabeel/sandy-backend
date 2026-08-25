"""The four seconds a chat reply spent re-reading a life that had not changed.

Production, on a two-message conversation, both messages identical in shape:

    [soul] total: 3465ms
    [soul] total: 4199ms

`get_persona_directives` rebuilds "what Sandy knows about you" from scratch on
every message — tasks, habits, books, journal, shopping, preferences,
relationships, lessons, the onboarding profile. Thirty-two of the forty-one
database round trips a turn waits for, and it is the same answer as last
message almost every time.

**A previous commit shipped the version stamp and never connected it.** The
module was written, the bumps were placed on every write path, and nothing ever
called `version_for` — so the machinery existed, cost a write per change, and
saved nothing. The log above is what that looks like: identical to before.

These tests are about the two ways a cache like this goes wrong.

* It does not hit — the thing above, plus the subtler version where a counter
  written on every single turn moves the key each time.
* It hits when it should not — a task added a second ago, and Sandy answering
  from the world before it.
"""
from __future__ import annotations

import mongomock
import pytest


U = "tenant-1"
P = {"user_id": U, "chat_id": U, "relation": "user", "permissions": "all",
     "is_guest": False}


@pytest.fixture()
def db():
    import app.db as appdb
    from app.agent.context_builder import clear_directives_cache

    database = mongomock.MongoClient()["t"]
    database["sandy_users"].insert_one({"_id": U, "user_id": U})
    appdb.configure(database)
    clear_directives_cache()
    try:
        yield database
    finally:
        clear_directives_cache()
        appdb.reset()


@pytest.fixture()
def builds(monkeypatch):
    """Counts how often the expensive half actually runs."""
    import app.agent.context_builder as cb

    calls = {"n": 0}
    real = cb._build_directive_blocks

    def _counted(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(cb, "_build_directive_blocks", _counted)
    return calls


def _directives(db, message: str = "", who: str = U):
    from app.agent.context_builder import get_persona_directives

    return get_persona_directives(who, who, db, message=message)


def test_a_second_message_does_not_rebuild_what_did_not_change(db, builds):
    from app.utils import user_profiles

    with user_profiles.active_user_profile_context(P):
        first = _directives(db)
        second = _directives(db)

    assert builds["n"] == 1, \
        "the cache is not connected — every message pays for the full rebuild"
    assert first == second


def test_adding_a_task_is_visible_on_the_very_next_message(db, builds):
    """**The failure that got the first attempt at this cut.**

    A TTL cache answers "what are my tasks" from before the task existed. The
    version stamp moves the moment the write lands, so the next read rebuilds.
    """
    from app.utils import user_profiles
    from app.utils.tenant_db import scoped

    with user_profiles.active_user_profile_context(P):
        _directives(db)
        assert builds["n"] == 1

        scoped(db, "sandy_tasks").insert_one({"text": "شراء حليب", "done": False})

        _directives(db)
        assert builds["n"] == 2, "Sandy would answer about a life one write old"


def test_a_write_by_the_other_worker_is_visible_too(db, builds):
    """Two gunicorn workers share nothing in memory. The stamp is in the
    database precisely so the invalidation crosses the process boundary — this
    simulates the far worker by bumping without touching this process's state."""
    from app.utils import user_profiles
    from app.utils.tenant_version import bump_for

    with user_profiles.active_user_profile_context(P):
        _directives(db)
        bump_for(U, collection="sandy_habits")
        _directives(db)

    assert builds["n"] == 2, "a change on the other worker never reaches this one"


def test_the_per_turn_interest_counter_does_not_defeat_the_cache(db, builds):
    """`track_message_interests` writes to `sandy_memories` on **every message**.

    It writes the `interest` label, and no cached block is built from that
    label — but the stamp is per collection, so left bumping it moved the key
    once per turn and the cache would never once have hit. It opts out at the
    call site (`scoped(..., bump=False)`), and this is what that is for.
    """
    from app.agent.interests_tracker import bump_interest
    from app.utils import user_profiles

    with user_profiles.active_user_profile_context(P):
        _directives(db)
        assert bump_interest("برمجة") is True
        _directives(db)

    assert builds["n"] == 1, \
        "the interest counter invalidates a cache it has nothing to do with"


def test_a_preference_written_the_normal_way_still_invalidates(db, builds):
    """The opt-out is for one counter, not for the collection. A style memory
    or a preference lands in the same `sandy_memories` and must be seen."""
    from app.utils import user_profiles
    from app.utils.tenant_db import scoped

    with user_profiles.active_user_profile_context(P):
        _directives(db)
        scoped(db, "sandy_memories", field="chat_id").insert_one(
            {"label": "preferences", "preference": "بحب الاختصار"})
        out = _directives(db)

    assert builds["n"] == 2
    assert "بحب الاختصار" in (out or ""), "a new preference never reached her"


def test_the_message_search_still_runs_on_a_cache_hit(db, monkeypatch, builds):
    """Only the message-independent half is cached. The keyword search over his
    life depends on what he just said, so a hit must not skip it."""
    import app.agent.context_builder as cb
    from app.utils import user_profiles

    seen: list = []
    monkeypatch.setattr(cb, "_safe_life_search",
                        lambda msg: seen.append(msg) or "[لقيت: كتاب]")
    monkeypatch.setattr(cb, "_index_life_in_background", lambda: None)

    with user_profiles.active_user_profile_context(P):
        first = _directives(db, message="شو كتابي")
        second = _directives(db, message="وين وصلت بالكتاب")

    assert builds["n"] == 1, "the cached half was rebuilt"
    assert seen == ["شو كتابي", "وين وصلت بالكتاب"], \
        "the cache swallowed the live search"
    assert "[لقيت: كتاب]" in (first or "") and "[لقيت: كتاب]" in (second or "")


def test_the_search_block_keeps_its_place_between_the_two_halves(db, monkeypatch):
    """Order is not cosmetic — it is the order Sandy reads them in. The cached
    piece is split in two around the live block for exactly this reason."""
    import app.agent.context_builder as cb
    from app.utils import user_profiles

    monkeypatch.setattr(cb, "_safe_life_snapshot", lambda: "[لقطة]")
    monkeypatch.setattr(cb, "_safe_life_search", lambda msg: "[بحث]")
    monkeypatch.setattr(cb, "_index_life_in_background", lambda: None)
    monkeypatch.setattr(cb, "get_onboarding_directive", lambda cid: "[ملف]")

    with user_profiles.active_user_profile_context(P):
        out = _directives(db, message="سؤال")

    assert out == "[لقطة]\n[بحث]\n[ملف]"


def test_an_unreadable_stamp_rebuilds_instead_of_guessing(db, monkeypatch, builds):
    """A cache that cannot check its key must miss, never assume."""
    import app.utils.tenant_version as tv
    from app.utils import user_profiles

    monkeypatch.setattr(tv, "_coll", lambda: None)

    with user_profiles.active_user_profile_context(P):
        _directives(db)
        _directives(db)

    assert builds["n"] == 2, "it served a cached block it could not verify"


def test_two_tenants_never_see_each_others_block(db, builds):
    """The cache is process-global and both workers serve every customer."""
    from app.utils import user_profiles
    from app.utils.tenant_db import scoped

    other = {**P, "user_id": "tenant-2", "chat_id": "tenant-2"}
    db["sandy_users"].insert_one({"_id": "tenant-2", "user_id": "tenant-2"})

    with user_profiles.active_user_profile_context(P):
        scoped(db, "sandy_memories", field="chat_id").insert_one(
            {"label": "preferences", "preference": "سرّ نبيل"})
        mine = _directives(db)

    with user_profiles.active_user_profile_context(other):
        theirs = _directives(db, who="tenant-2")

    assert "سرّ نبيل" in (mine or "")
    assert "سرّ نبيل" not in (theirs or ""), "one customer's block served to another"


def test_deleting_an_account_drops_its_cached_block(db):
    """Otherwise the block outlives the person who asked to be forgotten."""
    from app.features.account_delete import delete_account
    from app.utils import user_profiles
    from app.utils.tenant_db import scoped

    with user_profiles.active_user_profile_context(P):
        scoped(db, "sandy_memories", field="chat_id").insert_one(
            {"label": "preferences", "preference": "سرّ نبيل"})
        assert "سرّ نبيل" in (_directives(db) or "")

    delete_account(U)

    from app.agent.context_builder import _DIRECTIVES_CACHE

    assert _DIRECTIVES_CACHE == {}, "a deleted account's context is still in memory"
    assert db["sandy_cache_stamps"].count_documents({"_id": U}) == 0


# ── What the hostile review found, before it was fixed ──────────────────────
#
# Three writers reach `sandy_memories` on a raw handle, so the tenant wrapper's
# stamp never fired for them. Each writes a label a cached block is built from,
# and each was invisible to the cache for as long as the account made no other
# change. These are the tests for that.


def test_telling_her_to_remember_something_reaches_the_next_reply(db, builds):
    """`memory_store` is the tool behind «ساندي تذكري إني…».

    It writes `user_fact` on a raw handle. The app's own `POST /api/memory`
    writes the identical document and bumps — so saving a fact from the app
    worked and telling Sandy did not, which is the worst shape a bug can take.
    """
    from app.agent.tools.schemas.mcp_tools import memory_store
    from app.utils import user_profiles

    class _Ctx:
        mongo_db = None

    with user_profiles.active_user_profile_context(P):
        _directives(db)
        _Ctx.mongo_db = db
        memory_store({"content": "بشتغل بالليل"}, _Ctx())
        out = _directives(db)

    assert builds["n"] == 2
    assert "بشتغل بالليل" in (out or ""), "she said «دوّنتها» and forgot it"


def test_a_style_correction_reaches_the_next_reply(db, builds):
    """«اختصري ردودك» — saved on a raw handle as `style_memory`, read back as a
    preference. Uncaught, she agrees to be brief and stays long forever."""
    from app.agent.style_memory import save_style_preference
    from app.utils import user_profiles

    with user_profiles.active_user_profile_context(P):
        _directives(db)
        assert save_style_preference(U, U, "اختصري ردودك", "ردودك طويلة", db) is True
        out = _directives(db)

    assert builds["n"] == 2
    assert "اختصري ردودك" in (out or ""), "the correction never reached her"


def test_a_conversation_summary_reaches_the_next_reply(db, builds, monkeypatch):
    """STM overflows into a summary written on a raw handle. Uncaught, she does
    not remember the conversation that just ended.

    The real `_summarize_to_ltm` is driven here, with the model call stubbed —
    reproducing the write by hand would have tested the test.
    """
    import app.agent.graph.graph as g
    from app.utils import user_profiles

    class _Resp:
        choices = [type("_C", (), {"message": type("_M", (), {
            "content": "حكينا عن السفر"})()})()]

    class _Client:
        chat = type("_Chat", (), {"completions": type("_Comp", (), {
            "create": staticmethod(lambda **kw: _Resp())})()})()

    monkeypatch.setattr(g, "_get_summary_client", lambda: _Client())
    monkeypatch.setattr(g, "_is_duplicate_memory", lambda *a, **k: False)
    monkeypatch.setattr(g, "AZURE_OPENAI_API_KEY", "test-key", raising=False)
    monkeypatch.setattr("app.config.AZURE_OPENAI_API_KEY", "test-key")

    with user_profiles.active_user_profile_context(P):
        _directives(db)
        g._summarize_to_ltm(U, U, [{"role": "user", "content": "بدي أسافر"}])
        out = _directives(db)

    assert db["sandy_memories"].count_documents(
        {"label": "conversation_summary"}) == 1, "the fixture never wrote a summary"
    assert builds["n"] == 2
    assert "حكينا عن السفر" in (out or "")


def test_a_failed_read_is_not_remembered_as_an_answer(db, monkeypatch, builds):
    """**One bad second must not become every message.**

    The readers degrade instead of raising: a Mongo hiccup makes the memories
    query return nothing and the snapshot come back empty. Nothing about a
    failure moves the version, so caching the result of one would answer
    "ما عندك ولا مهمة" to a user with twelve, until his next write.
    """
    import app.agent.context_builder as cb
    from app.utils import user_profiles

    broken = {"yes": True}
    monkeypatch.setattr(
        cb, "_safe_life_snapshot",
        lambda: None if broken["yes"] else "[لقطة: ١٢ مهمة]")

    with user_profiles.active_user_profile_context(P):
        assert "[لقطة" not in (_directives(db) or "")
        broken["yes"] = False
        out = _directives(db)

    assert builds["n"] == 2, "a failed read was cached as if it were data"
    assert "[لقطة: ١٢ مهمة]" in (out or "")


def test_a_failed_list_read_is_not_remembered_either(db, monkeypatch):
    """Same rule for the five lists the keyword search scans."""
    import app.agent.life_snapshot as ls

    ls.clear_lists_cache()
    from app.utils import user_profiles

    broken = {"yes": True}

    def _safe(fn, what):
        if what == "tasks" and broken["yes"]:
            return None
        return []

    monkeypatch.setattr(ls, "_safe", _safe)

    with user_profiles.active_user_profile_context(P):
        ls._searchable_lists()
        broken["yes"] = False
        assert ls._searchable_lists()["tasks"] == [], \
            "a store that raised was cached as a store that is empty"
    ls.clear_lists_cache()


def test_a_streak_does_not_outlive_the_day_it_was_computed(db, monkeypatch, builds):
    """The one staleness a version stamp cannot see.

    A habit streak breaks at midnight with nobody writing anything, and the
    reminders line filters on "since half an hour ago". Both are functions of
    the clock, so the ceiling — not the version — is what catches them.
    """
    import app.agent.context_builder as cb
    from app.utils import user_profiles

    clock = {"t": 1000.0}
    monkeypatch.setattr(cb.time, "monotonic", lambda: clock["t"])

    with user_profiles.active_user_profile_context(P):
        _directives(db)
        clock["t"] += cb._MAX_AGE_S - 1
        _directives(db)
        assert builds["n"] == 1, "the ceiling is far too low to be a cache"
        clock["t"] += 2
        _directives(db)

    assert builds["n"] == 2, "a block computed from the clock never expires"
