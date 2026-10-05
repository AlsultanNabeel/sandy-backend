"""What fell out of the turns reaches the prompt: this conversation's summary, and the
other conversations closest to the message."""
from __future__ import annotations

from brain_fakes import A, B, brain_db  # noqa: F401

from app.blocks import entries
from app.brain import context
from app.utils.user_profiles import active_user_profile_context


def test_the_threads_own_summary_is_in_the_prompt(brain_db, monkeypatch):  # noqa: F811
    monkeypatch.setattr(entries, "embed_text", lambda text: None)
    with active_user_profile_context(A):
        entries.add("summary", "اتفقنا إنه السفر بأول الشهر", {"thread_id": "t1"})
        entries.add("summary", "محادثة تانية عن الشغل", {"thread_id": "t2"})
        system = context.build_system("userA", "مرحبا", [], thread_id="t1")
    assert "قبل هيك بهالمحادثة" in system and "السفر بأول الشهر" in system
    assert "عن الشغل" not in system


def test_only_the_newest_summaries_of_the_thread_oldest_first(brain_db, monkeypatch):  # noqa: F811
    monkeypatch.setattr(entries, "embed_text", lambda text: None)
    from datetime import datetime, timedelta, timezone

    # Minutes apart, as real summaries are: Mongo keeps milliseconds, and three written
    # in one millisecond have no order to test.
    start = datetime.now(timezone.utc) - timedelta(hours=1)
    with active_user_profile_context(A):
        for i in range(context.THREAD_SUMMARIES + 1):
            entries.add("summary", f"ملخص رقم {i}", {"thread_id": "t1"},
                        at=start + timedelta(minutes=10 * i))
        block = context.conversation_block("t1", "مرحبا")
    assert "ملخص رقم 0" not in block
    assert block.index("ملخص رقم 1") < block.index("ملخص رقم 2")


def test_a_related_past_conversation_comes_in_but_not_this_ones_twice(brain_db, monkeypatch):  # noqa: F811
    monkeypatch.setattr(entries, "embed_text", lambda text: None)
    with active_user_profile_context(A):
        entries.add("summary", "حكينا عن رحلة البحر الميت", {"thread_id": "old"})
        entries.add("summary", "رحلة البحر بهالمحادثة", {"thread_id": "t1"})
        block = context.conversation_block("t1", "شو صار برحلة البحر الميت")
    assert "من محادثات قبل" in block and "رحلة البحر الميت" in block
    assert block.count("رحلة البحر بهالمحادثة") == 1


def test_a_short_message_looks_up_no_past_conversation(brain_db, monkeypatch):  # noqa: F811
    monkeypatch.setattr(entries, "embed_text", lambda text: None)
    with active_user_profile_context(A):
        entries.add("summary", "حكينا عن البحر", {"thread_id": "old"})
        assert context.conversation_block("t1", "البحر") == ""


def test_another_tenants_summaries_never_reach_the_prompt(brain_db, monkeypatch):  # noqa: F811
    monkeypatch.setattr(entries, "embed_text", lambda text: None)
    with active_user_profile_context(B):
        entries.add("summary", "سر ب عن رحلة البحر", {"thread_id": "t1"})
    with active_user_profile_context(A):
        assert context.conversation_block("t1", "شو صار برحلة البحر") == ""
