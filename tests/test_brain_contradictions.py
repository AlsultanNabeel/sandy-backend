"""One turn does not undo what it just did (eval, 29 Oct 2026, on the real model): «no, I meant
60 not 50» updated the expense and deleted it in the same step, and «turn off the AC in an
hour» scheduled it and turned it off at once. The second call is refused (`brain.takeback`)
and the first stands; the refusal is the model's to read, and the user reads its answer."""
from __future__ import annotations

import json
from types import SimpleNamespace as NS

import pytest
from brain_fakes import A, ScriptedModel, brain_db, call, text_reply, tools_reply  # noqa: F401

from app.blocks import entries
from app.brain import loop
from app.utils.user_profiles import active_user_profile_context


@pytest.fixture
def sent(monkeypatch):
    """What reached the AC: a registered device on a stand-in broker."""
    from brain_fakes import on_node

    from app.features import device_store
    out = []
    monkeypatch.setattr("app.integrations.device_publisher.get_device_publisher",
                        lambda: NS(send_to_topic=lambda topic, payload: out.append(payload) or True))
    with active_user_profile_context(A):
        device_store.add_device("ac", "AC", "switch", on_node("ac"))
    return out


def _turn(model, message):
    with active_user_profile_context(A):
        return loop.run_turn(message, user_id="userA", chat_id="userA", source="web",
                             complete=model)


def _result(model, call_id):
    return json.loads(next(m for m in model.seen[1] if m.get("tool_call_id") == call_id)["content"])


def _corrected_then_deleted(message, answer="ok"):
    with active_user_profile_context(A):
        rid = entries.add("expense", "gas", data={"amount": 50})
    model = ScriptedModel(tools_reply(call("log_update", "c1", id=rid, amount=60),
                                      call("log_delete", "c2", id=rid)),
                          text_reply(answer))
    return model, _turn(model, message)


@pytest.mark.parametrize("message", ["no, I meant 60 not 50", "لا قصدي ستين مش خمسين"])
def test_a_row_corrected_in_the_turn_is_not_deleted_in_it(brain_db, message):  # noqa: F811
    model, _ = _corrected_then_deleted(message)
    with active_user_profile_context(A):
        rows = entries.list_entries("expense")
    assert [r["data"]["amount"] for r in rows] == [60]
    refusal = _result(model, "c2")
    assert not refusal["ok"] and "corrected" in refusal["error"]


@pytest.mark.parametrize("message", ["turn off the AC in an hour", "طفّي المكيف بعد ساعة"])
def test_a_device_set_for_later_is_not_switched_now(brain_db, sent, message):  # noqa: F811
    model = ScriptedModel(tools_reply(call("schedule", "c1", kind="scene", text="AC off",
                                           in_minutes=60, device="ac", value="off"),
                                      call("device_control", "c2", device="ac", action="off")),
                          text_reply("ok"))
    _turn(model, message)
    assert sent == []
    refusal = _result(model, "c2")
    assert not refusal["ok"] and "later" in refusal["error"]


def test_a_device_switched_now_and_set_otherwise_for_later_is_both(brain_db, sent):  # noqa: F811
    model = ScriptedModel(tools_reply(call("schedule", "c1", kind="scene", text="AC off",
                                           in_minutes=60, device="ac", value="off"),
                                      call("device_control", "c2", device="ac", action="on")),
                          text_reply("ok"))
    _turn(model, "turn on the AC now and off in an hour")
    assert sent == ["on"]


# Asked for now and for later, both run: the refusal is for a command asked for later only
# (review of 29 Oct 2026). «now» in the message is what says so.
@pytest.mark.parametrize("message", [
    "turn off the AC now and again at 11pm",
    "طفّي المكيف هلّق ومرة كمان الساعة احدعش",
])
def test_a_device_asked_for_now_and_for_later_is_both(brain_db, sent, message):  # noqa: F811
    model = ScriptedModel(tools_reply(call("schedule", "c1", kind="scene", text="AC off",
                                           when="23:00", device="ac", value="off"),
                                      call("device_control", "c2", device="ac", action="off")),
                          text_reply("ok"))
    _turn(model, message)
    assert sent == ["off"]


# The refusal is the model's, never the user's (review of 29 Oct 2026): a reply the honesty
# check replaced said «I didn't delete what I just corrected» to someone who asked no delete.
@pytest.mark.parametrize("message, claim", [
    ("no, I meant 60 not 50", "Deleted it ✅"),
    ("لا قصدي ستين مش خمسين", "حذفته ✅"),
])
def test_the_refusal_is_read_by_the_model_not_the_user(brain_db, message, claim):  # noqa: F811
    model, state = _corrected_then_deleted(message, answer=claim)
    assert "reply" not in _result(model, "c2")
    assert state["final_response"] == _result(model, "c1")["reply"]


# The target the tools resolved, not the words the model passed (review of 29 Oct 2026): an
# update and a delete with no id both name the newest row, and «AC» and «ac» are one device.
@pytest.mark.parametrize("message", ["no, I meant 60 not 50", "لا قصدي ستين مش خمسين"])
def test_the_newest_row_corrected_with_no_id_is_not_deleted(brain_db, message):  # noqa: F811
    with active_user_profile_context(A):
        entries.add("expense", "gas", data={"amount": 50})
    model = ScriptedModel(tools_reply(call("log_update", "c1", kind="expense", amount=60),
                                      call("log_delete", "c2", kind="expense")),
                          text_reply("ok"))
    _turn(model, message)
    with active_user_profile_context(A):
        rows = entries.list_entries("expense")
    assert [r["data"]["amount"] for r in rows] == [60]


@pytest.mark.parametrize("message", ["turn off the AC in an hour", "طفّي المكيف بعد ساعة"])
def test_a_device_set_for_later_by_its_label_is_not_switched_now_by_its_name(
        brain_db, sent, message):  # noqa: F811
    model = ScriptedModel(tools_reply(call("schedule", "c1", kind="scene", text="AC off",
                                           in_minutes=60, device="AC", value="off"),
                                      call("device_control", "c2", device="ac", action="off")),
                          text_reply("ok"))
    _turn(model, message)
    assert sent == []


# «طفّي المكيف بعد ساعة» on the real model (review, 30 Oct 2026): it scheduled the AC with no
# command, the schedule was refused, and it switched the AC off at once, saying «طفّيت المكيف».
# The command comes from his own words when the model leaves it out; a timer refused in a turn
# leaves the device alone in that turn; and she says she could not.
@pytest.mark.parametrize("message, text", [("طفّي المكيف بعد ساعة", "طفي المكيف"),
                                           ("turn off the AC in an hour", "turn off the AC")])
def test_a_timer_with_no_command_takes_it_from_his_words(brain_db, sent, message, text):  # noqa: F811
    from app.blocks import schedules
    model = ScriptedModel(tools_reply(call("schedule", "c1", kind="scene", text=text,
                                           in_minutes=60, device="ac")),
                          text_reply("ok"))
    _turn(model, message)
    assert _result(model, "c1")["ok"] and sent == []
    with active_user_profile_context(A):
        [row] = [r for r in schedules.list_schedules("scene") if (r.get("payload") or {}).get("asked")]
    assert row["payload"]["device"] == "ac" and row["payload"]["value"] == "off"


@pytest.mark.parametrize("message, language", [("طفّي المكيف بعد ساعة", "ar"),
                                               ("turn off the AC in an hour", "en")])
def test_a_refused_timer_never_switches_the_device_now_and_says_so(brain_db, sent, message, language):  # noqa: F811
    from app.brain import lang
    model = ScriptedModel(tools_reply(call("schedule", "c1", kind="scene", text="AC",
                                           in_minutes=60, device="ac", value="explode")),
                          tools_reply(call("device_control", "c2", device="ac", action="off")),
                          text_reply("طفّيت المكيف ✅" if language == "ar" else "I turned off the AC ✅"))
    state = _turn(model, message)
    assert sent == []
    assert not _result(model, "c1")["ok"]
    refusal = json.loads(next(m for m in model.seen[2] if m.get("tool_call_id") == "c2")["content"])
    assert not refusal["ok"]
    reply = state["final_response"]
    said = lang.PHRASES["timer_failed"][language].split("{")[0].strip()
    assert said in reply and ("طفّيت" not in reply and "turned off" not in reply)
