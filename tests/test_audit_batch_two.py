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
