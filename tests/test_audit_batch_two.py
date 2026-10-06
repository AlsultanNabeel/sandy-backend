"""Regressions from the audit plan, batch two: confirmation, rewind and undo in the brain.

Each test failed before its fix and names what the user saw.
"""
from __future__ import annotations

from brain_fakes import A, ScriptedModel, brain_db, call, text_reply, tools_reply  # noqa: F401

from app.blocks import items
from app.brain import loop
from app.utils.user_profiles import active_user_profile_context


def _turn(model, message, pending=None, **kw):
    with active_user_profile_context(A):
        return loop.run_turn(message, user_id="userA", chat_id="userA", source="web",
                             pending_state=pending, complete=model, **kw)


def _open(lst="tasks"):
    with active_user_profile_context(A):
        return [i["text"] for i in items.list_items(lst)]


# ── W1. A yes to one delete is not a yes to the next request ─────────────────

def test_a_yes_with_a_new_delete_after_it_asks_again(brain_db):  # noqa: F811
    with active_user_profile_context(A):
        gym = items.add("tasks", "روح عالجيم")
        report = items.add("tasks", "تقرير الشغل")
    held = _turn(ScriptedModel(tools_reply(call("list_update", id=gym, delete=True))),
                 "احذفي مهمة الجيم")["pending_state"]
    model = ScriptedModel(tools_reply(call("list_update", id=report, delete=True)))
    state = _turn(model, "اه واحذفي كمان مهمة التقرير", pending=held)
    assert "روح عالجيم" not in _open(), "the held delete itself runs"
    assert "تقرير الشغل" in _open(), "the delete in the same line ran with no question"
    assert "متأكد إنك بدك تحذف «تقرير الشغل»" in state["final_response"]
    assert state["pending_state"] is not None


# ── W2. A written-out time in the past is refused, never read as a clock ─────

def test_an_iso_time_in_the_past_or_too_far_is_refused(brain_db):  # noqa: F811
    from datetime import datetime, timedelta

    from app.brain import when

    now = datetime.now().replace(microsecond=0)
    with active_user_profile_context(A):
        assert when.parse_when((now - timedelta(hours=1)).isoformat()) is None, \
            "a reminder an hour ago was saved for ten at night"
        assert when.parse_when((now + timedelta(days=500)).isoformat()) is None
        assert when.parse_when((now + timedelta(hours=2)).isoformat()) is not None
        assert when.parse_when("بكرا الساعة 5") is not None, "words still go to the clock"


# ── W3. «Which one?» is answered by the opening of the reply, not any number in it ──

def _two_milks():
    with active_user_profile_context(A):
        a = items.add("shopping", "حليب بقر")
        b = items.add("shopping", "حليب لوز")
    held = _turn(ScriptedModel(tools_reply(call("list_update", list="shopping",
                                                match_text="حليب", done=True))),
                 "شطبي الحليب")["pending_state"]
    assert held and held["action"] == "choose"
    return a, b, held


def _done(iid):
    with active_user_profile_context(A):
        return items.get(iid)["done"]


def test_a_number_further_on_is_a_new_request_not_a_pick(brain_db):  # noqa: F811
    a, b, held = _two_milks()
    model = ScriptedModel(tools_reply(call("list_add", list="shopping", text="بيض", qty=2)),
                          text_reply("ضفت بيض"))
    _turn(model, "ضيفي ٢ بيض للتسوق", pending=held)
    assert not _done(b), "«٢» picked the second milk and ticked it"
    assert model.seen, "the request itself never reached the model"
    assert "بيض" in _open("shopping")


def test_all_before_more_words_is_not_all(brain_db):  # noqa: F811
    a, b, held = _two_milks()
    _turn(ScriptedModel(text_reply("حلو")), "كل شي تمام", pending=held)
    assert not _done(a) and not _done(b), "«كل شي تمام» ticked both"


def test_a_pick_then_a_request_does_both(brain_db):  # noqa: F811
    from app.brain import confirm

    a, b, held = _two_milks()
    assert confirm.pick("التانية", held["candidates"]) == ([b], False)
    assert confirm.pick("الأولى والتالتة", held["candidates"])[0] == [a]
    assert confirm.pick("كلهم", held["candidates"]) == ([a, b], False)
    model = ScriptedModel(tools_reply(call("list_add", list="shopping", text="خبز")),
                          text_reply("ضفت خبز"))
    state = _turn(model, "التانية وضيفي خبز", pending=held)
    assert _done(b) and not _done(a)
    assert "خبز" in _open("shopping") and "اختار" in model.seen[0][0]["content"]
    assert state["pending_state"] is None


# ── W7. A held delete does not swallow the answer to the rest of the line ────

def test_the_model_s_answer_stays_beside_the_held_question(brain_db):  # noqa: F811
    with active_user_profile_context(A):
        gym = items.add("tasks", "روح عالجيم")
    model = ScriptedModel(tools_reply(call("list_update", id=gym, delete=True)),
                          text_reply("بكرا عندك اجتماع الساعة عشرة."))
    state = _turn(model, "احذفي مهمة الجيم وشو عندي بكرا؟")
    assert state["final_response"].startswith("بكرا عندك اجتماع الساعة عشرة.\nمتأكد إنك بدك تحذف"), \
        "tomorrow's answer was dropped and only the question came back"
    assert state["pending_state"] is not None
