"""Delete / bulk wait for a yes, read by the existing Arabic yes/no resolver."""
from __future__ import annotations

import pytest
from brain_fakes import A, ScriptedModel, brain_db, call, text_reply, tools_reply  # noqa: F401

from app.agent.pending_store import load_pending_state, save_pending_state
from app.blocks import items
from app.brain import confirm, loop, voice
from app.utils.user_profiles import active_user_profile_context


def _turn(model, message, pending=None):
    with active_user_profile_context(A):
        return loop.run_turn(message, user_id="userA", chat_id="userA", source="web",
                             pending_state=pending, complete=model)


def _ask_delete(iid):
    model = ScriptedModel(tools_reply(call("list_update", id=iid, delete=True)))
    state = _turn(model, "احذفي مهمة الجيم")
    assert len(model.seen) == 1  # the question is deterministic, no second call
    return state


@pytest.fixture
def gym(brain_db):  # noqa: F811
    with active_user_profile_context(A):
        return items.add("tasks", "روح عالجيم")


def _exists(iid):
    with active_user_profile_context(A):
        return items.get(iid) is not None


def test_delete_asks_and_holds(gym):
    state = _ask_delete(gym)
    assert state["final_response"].startswith("متأكد إنك بدك تحذف «روح عالجيم»")
    assert state["pending_state"]["type"] == confirm.PENDING_TYPE
    assert _exists(gym)


@pytest.mark.parametrize("yes", ["اه صح", "آه", "اه 👍", "نعم", "تمام", "ok"])
def test_arabic_yes_runs_it_without_a_model_call(gym, yes):
    held = _ask_delete(gym)["pending_state"]
    model = ScriptedModel()
    state = _turn(model, yes, pending=held)
    assert model.seen == [] and state["pending_state"] is None
    assert "حذفت" in state["final_response"]
    assert not _exists(gym)


@pytest.mark.parametrize("no", ["لا", "لأ", "بلاش", "الغيها", "اه بس لا"])
def test_arabic_no_cancels(gym, no):
    held = _ask_delete(gym)["pending_state"]
    state = _turn(ScriptedModel(), no, pending=held)
    assert state["final_response"] == confirm.CANCELLED_REPLY
    assert state["pending_state"] is None and _exists(gym)


def test_anything_else_drops_the_hold_and_is_a_normal_turn(gym):
    held = _ask_delete(gym)["pending_state"]
    model = ScriptedModel(text_reply("الجو حلو اليوم"))
    state = _turn(model, "كيف الطقس؟", pending=held)
    assert len(model.seen) == 1 and state["pending_state"] is None and _exists(gym)


def test_an_expired_hold_is_ignored(gym):
    held = dict(_ask_delete(gym)["pending_state"], expires_at="2000-01-01T00:00:00+00:00")
    model = ScriptedModel(text_reply("شو قصدك؟"))
    state = _turn(model, "اه", pending=held)
    assert len(model.seen) == 1 and _exists(gym) and state["pending_state"] is None


def test_the_hold_round_trips_through_the_pending_store(gym, brain_db):  # noqa: F811
    held = _ask_delete(gym)["pending_state"]
    save_pending_state("userA", "userA", brain_db, held)
    assert confirm.live(load_pending_state("userA", "userA", brain_db))["tool"] == "list_update"


def test_voice_holds_then_confirm_tool_resolves_with_the_same_resolver(gym):
    with active_user_profile_context(A):
        out = voice.dispatch("list_update", {"id": gym, "delete": True}, "userA")
        assert "متأكد" in out["reply"] and "ok" not in out
        assert _exists(gym)
        assert "مرة تانية" in voice.dispatch("confirm", {"answer": "يمكن"}, "userA")["reply"]
        out = voice.dispatch("confirm", {"answer": "اه صح"}, "userA")
        assert out["ok"] and not _exists(gym)
        assert "ما في إشي" in voice.dispatch("confirm", {"answer": "اه"}, "userA")["reply"]


def test_voice_cancel(gym):
    with active_user_profile_context(A):
        voice.dispatch("list_update", {"id": gym, "delete": True}, "userA")
        out = voice.dispatch("confirm", {"answer": "لأ"}, "userA")
    assert out["reply"] == confirm.CANCELLED_REPLY and _exists(gym)


def test_voice_marks_what_did_not_happen(brain_db):  # noqa: F811
    with active_user_profile_context(A):
        out = voice.dispatch("list_update", {"match_text": "ولا إشي", "done": True}, "userA")
    assert out["ok"] is False and out["reply"].startswith("[لم يُنفَّذ]")
