"""Tenant isolation through the brain: user A never sees or touches user B's rows."""
from __future__ import annotations

from brain_fakes import A, B, ScriptedModel, brain_db, call, text_reply, tools_reply  # noqa: F401

from app.utils.ltm_crypto import encrypt_field
from app.blocks import entries, items, schedules
from app.brain import context, loop, tools
from app.brain.ctx import TurnCtx
from app.utils.user_profiles import active_user_profile_context


def _seed_b():
    with active_user_profile_context(B):
        entries.add("journal", "سر بيانات ب")
        entries.add("fact", "ب بحب القهوة")
        iid = items.add("tasks", "مهمة ب السرية")
    return iid


def test_recall_never_returns_the_other_tenants_rows(brain_db):  # noqa: F811
    b_item = _seed_b()
    with active_user_profile_context(A):
        entries.add("journal", "بيانات أ")
        rows = tools.execute("recall", {}, TurnCtx(user_id="userA"))["rows"]
        assert [r["text"] for r in rows] == ["بيانات أ"]
        assert tools.execute("recall", {"query": "السرية"}, TurnCtx(user_id="userA"))["count"] == 0
        # Not by id either.
        out = tools.execute("list_update", {"id": b_item, "done": True}, TurnCtx(user_id="userA"))
        assert out["ok"] is False
    with active_user_profile_context(B):
        assert items.get(b_item)["done"] is False


def test_the_prompt_carries_only_this_tenants_memory(brain_db):  # noqa: F811
    _seed_b()
    with active_user_profile_context(A):
        entries.add("fact", "أ اسمه سامي")
        system = context.build_system("userA", "قهوة بيانات", [])
    assert "أ اسمه سامي" in system
    assert "ب بحب القهوة" not in system and "سر بيانات ب" not in system


def test_encrypted_facts_are_decrypted_for_the_prompt(brain_db, monkeypatch):  # noqa: F811
    from cryptography.fernet import Fernet
    from app.utils import ltm_crypto
    monkeypatch.setattr(ltm_crypto, "_fernet", Fernet(Fernet.generate_key()))
    with active_user_profile_context(A):
        entries.add("fact", encrypt_field("بحب الشاي"), {"encrypted": True})
        assert "بحب الشاي" in context.facts_block()


def test_similar_entries_rank_by_vector(brain_db, monkeypatch):  # noqa: F811
    with active_user_profile_context(A):
        entries.add("journal", "بحر", embedding=[1.0, 0.0])
        entries.add("journal", "جبل", embedding=[0.0, 1.0])
        monkeypatch.setattr(entries, "embed_text", lambda text: [0.9, 0.1])
        assert [e["text"] for e in context.similar_entries("بدي أروح سباحة بكرا", k=1)] == ["بحر"]
    with active_user_profile_context(B):
        assert context.similar_entries("بدي أروح سباحة بكرا") == []


def test_a_turn_with_no_tenant_writes_nothing(brain_db):  # noqa: F811
    model = ScriptedModel(tools_reply(call("list_add", list="tasks", text="x")),
                          text_reply("ما زبط"))
    loop.run_turn("ضيفي x", user_id="", chat_id="", complete=model)
    assert brain_db["sandy_items"].count_documents({}) == 0
    with active_user_profile_context(A):
        assert schedules.list_schedules() == []


def test_the_prompt_shows_whats_open_with_ids_and_never_ciphertext(brain_db):  # noqa: F811
    from app.blocks import items, schedules
    from datetime import datetime, timedelta, timezone
    with active_user_profile_context(A):
        tid = items.add("tasks", "أخلص التقرير")
        sid = schedules.add("reminder", "انو آكل", datetime.now(timezone.utc) + timedelta(hours=1))
        entries.add("fact", "يشجع برشلونة", embed=False)
        entries.add("fact", "يشجع  برشلونة", embed=False)      # the same fact twice
        entries.add("fact", "احكي", embed=False)                 # a one-word scrap
        entries.add("fact", "enc:not-decryptable", embed=False)  # ciphertext with no key
        system = context.build_system("userA", "غيري وقت تذكير الأكل")
    assert f"#{tid}" in system and f"#{sid}" in system
    assert system.count("برشلونة") == 1
    assert "- احكي" not in system and "enc:" not in system


def test_misheard_audio_is_left_out_of_the_history():
    turns = [{"role": "user", "content": "<noise>"},
             {"role": "user", "content": "お待たせいたしました"},
             {"role": "user", "content": "مرحبا"}]
    assert [m["content"] for m in context.history_messages(turns)] == ["مرحبا"]
