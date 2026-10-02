"""Delete / bulk wait for a yes, read by the Arabic yes/no resolver."""
from __future__ import annotations

import pytest
from brain_fakes import A, ScriptedModel, brain_db, call, text_reply, tools_reply  # noqa: F401

from app.blocks import items
from app.brain import confirm, loop, voice
from app.brain import pending as P
from app.utils.user_profiles import active_user_profile_context


def _turn(model, message, pending=None):
    with active_user_profile_context(A):
        return loop.run_turn(message, user_id="userA", chat_id="userA", source="web",
                             pending_state=pending, complete=model)


def _ask_delete(iid):
    model = ScriptedModel(tools_reply(call("list_update", id=iid, delete=True)))
    state = _turn(model, "احذفي مهمة الجيم")
    # The model is told the delete waits and goes on; the question itself is ours.
    assert len(model.seen) == 2 and '"held": true' in model.seen[1][-1]["content"]
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


@pytest.mark.parametrize("yes", ["اه صح", "آه", "اه 👍", "نعم", "تمام", "ok",
                                 "اه متأكد احذفيها يا ساندي", "خلص احذفيها", "مش مشكلة احذفي"])
def test_arabic_yes_runs_it_without_a_model_call(gym, yes):
    held = _ask_delete(gym)["pending_state"]
    model = ScriptedModel()
    state = _turn(model, yes, pending=held)
    assert model.seen == [] and state["pending_state"] is None
    assert "حذفت" in state["final_response"]
    assert not _exists(gym)


@pytest.mark.parametrize("no", ["لا", "لأ", "بلاش", "الغيها", "اه بس لا", "خلص", "لا تحذفها"])
def test_arabic_no_cancels(gym, no):
    held = _ask_delete(gym)["pending_state"]
    state = _turn(ScriptedModel(), no, pending=held)
    assert state["final_response"] == confirm.CANCELLED_REPLY
    assert state["pending_state"] is None and _exists(gym)


def test_a_yes_with_more_runs_it_and_hands_the_rest_to_the_model(gym):
    held = _ask_delete(gym)["pending_state"]
    model = ScriptedModel(tools_reply(call("list_add", list="shopping", text="خبز")))
    state = _turn(model, "اه وضيفي خبز", pending=held)
    assert not _exists(gym)
    assert "حذفت" in model.seen[0][0]["content"]          # told what the yes already did
    assert state["final_response"].startswith("حذفت «روح عالجيم» ✅\n")
    with active_user_profile_context(A):
        assert [i["text"] for i in items.list_items("shopping")] == ["خبز"]


def test_a_no_with_more_hands_the_rest_to_the_model(gym):
    held = _ask_delete(gym)["pending_state"]
    model = ScriptedModel(tools_reply(call("list_update", id=gym, done=True)))
    state = _turn(model, "لا، بس خلّصيها", pending=held)
    assert "قال لأ" in model.seen[0][0]["content"]
    assert not state["final_response"].startswith(confirm.CANCELLED_REPLY)
    with active_user_profile_context(A):
        assert items.get(gym)["done"]


def test_an_unclear_answer_is_answered_and_asked_once_more_then_let_go(gym):
    held = _ask_delete(gym)["pending_state"]
    state = _turn(ScriptedModel(text_reply("الجو حلو اليوم")), "كيف الطقس؟", pending=held)
    assert state["final_response"].startswith("الجو حلو اليوم\nمتأكد إنك بدك تحذف")
    assert state["pending_state"]["asked_again"]
    state = _turn(ScriptedModel(text_reply("ههه")), "احكيلي نكتة", pending=state["pending_state"])
    assert state["pending_state"] is None and state["final_response"] == "ههه" and _exists(gym)


def test_two_deletes_in_one_turn_wait_as_one_question(brain_db):  # noqa: F811
    with active_user_profile_context(A):
        a, b = items.add("tasks", "مهمة أ"), items.add("tasks", "مهمة ب")
    model = ScriptedModel(tools_reply(call("list_update", id=a, delete=True),
                                      call("list_update", id=b, delete=True)))
    state = _turn(model, "احذفي التنتين")
    assert "«مهمة أ»" in state["final_response"] and "«مهمة ب»" in state["final_response"]
    _turn(ScriptedModel(), "اه", pending=state["pending_state"])
    with active_user_profile_context(A):
        assert items.get(a) is None and items.get(b) is None


def test_what_was_done_is_said_with_the_question_and_the_steps_after_it_run(gym):
    model = ScriptedModel(
        tools_reply(call("list_update", id=gym, delete=True)),
        tools_reply(call("list_add", list="tasks", text="روح عالمسبح")),
        text_reply("تمام"))
    state = _turn(model, "احذفي الجيم وحطي المسبح بداله")
    assert state["final_response"].startswith("ضفت «روح عالمسبح» ✅\nمتأكد إنك بدك تحذف")
    with active_user_profile_context(A):
        assert "روح عالمسبح" in [i["text"] for i in items.list_items("tasks")]
    assert _exists(gym)


def test_an_expired_hold_is_ignored(gym):
    held = dict(_ask_delete(gym)["pending_state"], expires_at="2000-01-01T00:00:00+00:00")
    model = ScriptedModel(text_reply("شو قصدك؟"))
    state = _turn(model, "اه", pending=held)
    assert len(model.seen) == 1 and _exists(gym) and state["pending_state"] is None


def test_the_hold_round_trips_through_the_pending_store(gym, brain_db):  # noqa: F811
    held = _ask_delete(gym)["pending_state"]
    P.save("userA", "userA", brain_db, held)
    assert confirm.live(P.load("userA", "userA", brain_db))["steps"][0]["tool"] == "list_update"


def test_voice_holds_then_confirm_tool_resolves_with_the_same_resolver(gym):
    with active_user_profile_context(A):
        out = voice.dispatch("list_update", {"id": gym, "delete": True}, "userA")
        assert "متأكد" in out["reply"] and "ok" not in out
        assert _exists(gym)
        assert "مرة تانية" in voice.dispatch("confirm", {"answer": "يمكن"}, "userA")["reply"]
        assert _exists(gym)
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


def test_voice_lets_go_after_a_second_unclear_answer_like_chat(gym):
    with active_user_profile_context(A):
        voice.dispatch("list_update", {"id": gym, "delete": True}, "userA")
        voice.dispatch("confirm", {"answer": "يمكن"}, "userA")
        out = voice.dispatch("confirm", {"answer": "يمكن بعدين"}, "userA")
        assert out["reply"].startswith("[لم يُنفَّذ]")
        assert "ما في إشي" in voice.dispatch("confirm", {"answer": "اه"}, "userA")["reply"]
    assert _exists(gym)


def test_voice_two_deletes_wait_as_one(brain_db):  # noqa: F811
    with active_user_profile_context(A):
        a, b = items.add("tasks", "مهمة أ"), items.add("tasks", "مهمة ب")
        voice.dispatch("list_update", {"id": a, "delete": True}, "userA")
        out = voice.dispatch("list_update", {"id": b, "delete": True}, "userA")
        assert "«مهمة أ»" in out["reply"] and "«مهمة ب»" in out["reply"]
        assert voice.dispatch("confirm", {"answer": "اه"}, "userA")["ok"]
        assert items.get(a) is None and items.get(b) is None
