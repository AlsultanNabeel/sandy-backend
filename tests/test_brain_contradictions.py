"""One turn does not undo what it just did (eval, 29 Oct 2026, on the real model): «no, I meant
60 not 50» updated the expense and deleted it in the same step, and «turn off the AC in an
hour» scheduled it and turned it off at once. The second call is refused, in the turn's
language, and the first stands."""
from __future__ import annotations

import pytest
from brain_fakes import A, ScriptedModel, brain_db, call, text_reply, tools_reply  # noqa: F401

from app.blocks import entries
from app.brain import lang, loop, tools
from app.utils.user_profiles import active_user_profile_context


def _ac():
    from brain_fakes import on_node

    from app.features import device_store
    with active_user_profile_context(A):
        device_store.add_device("ac", "AC", "switch", on_node("ac"))


def _turn(model, message):
    with active_user_profile_context(A):
        return loop.run_turn(message, user_id="userA", chat_id="userA", source="web",
                             complete=model)


@pytest.mark.parametrize("message, language", [
    ("no, I meant 60 not 50", "en"),
    ("لا قصدي ستين مش خمسين", "ar"),
])
def test_a_row_corrected_in_the_turn_is_not_deleted_in_it(brain_db, message, language):  # noqa: F811
    with active_user_profile_context(A):
        rid = entries.add("expense", "gas", data={"amount": 50})
    model = ScriptedModel(tools_reply(call("log_update", "c1", id=rid, amount=60),
                                      call("log_delete", "c2", id=rid)),
                          text_reply("ok"))
    _turn(model, message)
    with active_user_profile_context(A):
        rows = entries.list_entries("expense")
    assert [r["data"]["amount"] for r in rows] == [60]
    refusal = next(m for m in model.seen[1] if m.get("tool_call_id") == "c2")["content"]
    assert lang.PHRASES["kept_corrected"][language] in refusal


@pytest.mark.parametrize("message, language", [
    ("turn off the AC in an hour", "en"),
    ("طفّي المكيف بعد ساعة", "ar"),
])
def test_a_device_set_for_later_is_not_switched_now(brain_db, monkeypatch, message, language):  # noqa: F811
    _ac()
    sent = []
    monkeypatch.setitem(tools.HANDLERS, "device_control",
                        lambda args, ctx: sent.append(args) or {"ok": True, "reply": "off"})
    model = ScriptedModel(tools_reply(call("schedule", "c1", kind="scene", text="AC off",
                                           in_minutes=60, device="ac", value="off"),
                                      call("device_control", "c2", device="ac", action="off")),
                          text_reply("ok"))
    _turn(model, message)
    assert sent == []
    refusal = next(m for m in model.seen[1] if m.get("tool_call_id") == "c2")["content"]
    assert lang.PHRASES["set_for_later"][language] in refusal


def test_a_device_switched_now_and_set_otherwise_for_later_is_both(brain_db, monkeypatch):  # noqa: F811
    _ac()
    sent = []
    monkeypatch.setitem(tools.HANDLERS, "device_control",
                        lambda args, ctx: sent.append(args) or {"ok": True, "reply": "on"})
    model = ScriptedModel(tools_reply(call("schedule", "c1", kind="scene", text="AC off",
                                           in_minutes=60, device="ac", value="off"),
                                      call("device_control", "c2", device="ac", action="on")),
                          text_reply("ok"))
    _turn(model, "turn on the AC now and off in an hour")
    assert sent == [{"device": "ac", "action": "on"}]
