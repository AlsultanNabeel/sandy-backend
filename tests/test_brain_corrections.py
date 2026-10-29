"""Correcting what was logged, forgetting a fact, putting the room back after a scene."""
from __future__ import annotations

import pytest
from brain_fakes import A, ScriptedModel, brain_db, call, on_node, tools_reply  # noqa: F401

from app.blocks import entries, items, schedules
from app.brain import context, loop, tools
from app.brain.ctx import TurnCtx
from app.utils.ltm_crypto import decrypt_field, encrypt_field
from app.utils.user_profiles import active_user_profile_context


@pytest.fixture
def tenant(brain_db):  # noqa: F811
    with active_user_profile_context(A):
        yield brain_db


def _run(name, confirmed=False, **args):
    ctx = TurnCtx(user_id="userA")
    ctx.confirmed = confirmed
    return tools.execute(name, args, ctx)


def test_a_wrong_amount_is_corrected_on_the_same_row(tenant):
    eid = entries.add("expense", "غدا", {"amount": 50, "category": "food"})
    assert f"#{eid}" in context.state_block() and "(50)" in context.state_block()
    out = _run("log_update", id=eid, amount=40)
    assert out["ok"]
    row = entries.get(eid)
    assert row["data"] == {"amount": 40, "category": "food"}
    assert len(entries.list_entries("expense")) == 1


def test_with_no_id_the_newest_of_the_kind_is_the_one(tenant):
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    entries.add("expense", "قهوة", {"amount": 5}, at=now - timedelta(minutes=5))
    newest = entries.add("expense", "غدا", {"amount": 50}, at=now)
    out = _run("log_delete", kind="expense")
    assert out["ok"] and "«غدا»" in out["reply"]
    assert entries.get(newest) is None and len(entries.list_entries("expense")) == 1


def test_a_changed_fact_is_updated_and_sealed_again(tenant):
    old = "ساكن بالزرقاء"
    sealed = encrypt_field(old)
    eid = entries.add("fact", sealed, {"encrypted": sealed != old}, embed=False)
    assert f"{old} #{eid}" in context.facts_block()
    assert _run("log_update", id=eid, text="ساكن بعمّان")["ok"]
    row = entries.get(eid)
    assert decrypt_field(row["text"]) == "ساكن بعمّان"
    assert row["data"].get("encrypted") == (sealed != old)


def test_forget_a_fact_is_gone_at_once(tenant):
    eid = entries.add("fact", "بحب القهوة كتير")
    assert _run("log_delete", match_text="القهوة")["ok"]
    assert entries.get(eid) is None


def test_undo_brings_back_a_cancelled_reminder(tenant):
    from datetime import datetime, timedelta, timezone
    sid = schedules.add("reminder", "الدوا", datetime.now(timezone.utc) + timedelta(hours=1))
    model = ScriptedModel(tools_reply(call("schedule_cancel", id=sid)))
    loop.run_turn("الغي تذكير الدوا", user_id="userA", chat_id="userA",
                  source="web", complete=model)
    assert schedules.get(sid)["status"] == "cancelled"
    loop.run_turn("لا رجّعيه", user_id="userA", chat_id="userA", source="web",
                  complete=ScriptedModel(tools_reply(call("undo"))))
    assert schedules.get(sid)["status"] == "pending"


def test_the_room_goes_back_to_how_it_was_before_the_scene(tenant, monkeypatch):
    from app.features import device_store, scene_store

    sent = []

    class _Client:
        def send_to_topic(self, topic, payload):
            sent.append((topic, payload))
            return True

    monkeypatch.setattr("app.integrations.device_publisher.get_device_publisher", lambda: _Client())
    device_store.add_device("lamp", "الضو", "dimmer", on_node("lamp"))
    device_store.set_state("lamp", "80")
    scene_store.add_scene("dim", actions=[{"device": "lamp", "value": "10"}])
    assert scene_store.apply_scene("dim")["sent"] == 1
    assert device_store.get_device("lamp")["state"] == "10"

    out = _run("room_restore")
    assert out["ok"] and sent[-1] == ("sandy/node/n1/lamp", "80")
    assert device_store.get_device("lamp")["state"] == "80"
    assert _run("room_restore")["ok"] is False      # once only


def test_items_are_untouched_by_a_log_correction(tenant):
    iid = items.add("tasks", "غدا")
    entries.add("expense", "غدا", {"amount": 50})
    _run("log_update", match_text="غدا", amount=45)
    assert items.get(iid)["text"] == "غدا"


# Taking back an add says what went (review of phase one): «شلت «جبنة»», not «put back as it
# was», which told him the cheese was still there.
@pytest.mark.parametrize("language, added, said", [("ar", "جبنة", "شلت «جبنة» ✅"),
                                                   ("en", "cheese", "Removed «cheese» ✅")])
def test_undoing_an_add_says_it_was_removed(tenant, language, added, said):
    from app.blocks import changes
    from app.brain import lang
    with changes.recording("t1"), lang.using(language):
        items.add("shopping", added)
    with lang.using(language):
        out = _run("undo")
    assert out["ok"] and out["reply"] == said
    assert items.list_items("shopping") == []


def test_undoing_an_edit_still_says_it_was_put_back(tenant):
    from app.blocks import changes
    from app.brain import lang
    iid = items.add("shopping", "حليب")
    with changes.recording("t1"):
        items.update(iid, text="حليب لوز")
    with lang.using("ar"):
        out = _run("undo")
    assert out["ok"] and out["reply"].startswith("رجّعته زي ما كان")


# «لا غلط ارجعي عنه» right after an add is an undo, not a delete (review of phase one): the
# prompt and the undo tool carry the example in both languages, and say an add is taken back
# by undo, not by list_delete. The real model is scored by the eval's «undo» cases.
def test_the_prompt_sends_taking_back_an_add_to_undo_in_both_languages(tenant):
    from app.brain import context
    system = context.build_system("userA", "لا غلط ارجعي عنه")
    undo = next(s for s in tools.openai_tools() if s["function"]["name"] == "undo")
    for words in ("لا غلط ارجعي عنه", "take it back"):
        assert words in system and words in undo["function"]["description"]
    assert "مش list_delete" in system
