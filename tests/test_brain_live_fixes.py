"""The four failures of the first live test of the new agent (2026-09-30)."""
from __future__ import annotations

import pytest
from brain_fakes import A, ScriptedModel, brain_db, call, tools_reply  # noqa: F401

from app.blocks import entries, items
from app.brain import confirm, loop, tools
from app.brain.ctx import TurnCtx
from app.utils.user_profiles import active_user_profile_context


def _run(name, **args):
    with active_user_profile_context(A):
        return tools.execute(name, args, TurnCtx(user_id="userA"))


def _turn(model, message, pending=None):
    with active_user_profile_context(A):
        return loop.run_turn(message, user_id="userA", chat_id="userA", source="web",
                             pending_state=pending, complete=model)


@pytest.fixture
def db(brain_db):  # noqa: F811
    return brain_db


# 1. «شو مهامي»: the word names the list, it is not text to match.
def test_recall_turns_a_list_word_into_the_list_filter(db):
    with active_user_profile_context(A):
        items.add("tasks", "تقرير المشروع")
        items.add("shopping", "بيض")
    out = _run("recall", query="مهامي")
    assert [r["text"] for r in out["rows"]] == ["تقرير المشروع"]


def test_recall_keeps_the_filter_when_leftover_words_match_nothing(db):
    with active_user_profile_context(A):
        entries.add("expense", "غدا", {"amount": 50.0}, embed=False)
    out = _run("recall", query="مصاريف هالشهر")
    assert out["count"] == 1 and out["rows"][0]["kind"] == "expense"


def test_recall_leaves_chat_summaries_out_unless_asked(db):
    with active_user_profile_context(A):
        entries.add("summary", "ملخص محادثة", embed=False)
        entries.add("note", "رقم الجار", embed=False)
    assert [r["kind"] for r in _run("recall")["rows"]] == ["note"]
    assert _run("recall", kind="summary")["count"] == 1


def test_open_items_come_before_done_ones(db):
    with active_user_profile_context(A):
        old = items.add("tasks", "قديمة")
        items.update(old, done=True)
        items.add("tasks", "جديدة")
    rows = _run("recall", list="tasks")["rows"]
    assert [r["done"] for r in rows] == [False, True]


# 2. An expense sent to list_add is sent back to remember.
def test_list_add_refuses_a_log_kind_and_names_the_right_tool(db):
    out = _run("list_add", list="expense", text="غدا")
    assert out["ok"] is False and "remember" in out["error"]


# 4. The same open item is not added twice.
def test_list_add_does_not_duplicate_an_open_item(db):
    first = _run("list_add", list="tasks", text="أشتري حليب")
    again = _run("list_add", list="tasks", text="اشتري  حليب")
    assert again["already"] and again["id"] == first["id"]
    with active_user_profile_context(A):
        assert len(items.list_items("tasks")) == 1


# 3. Two rows match: ask which, then «الأولى» picks it and the delete asks for a yes.
@pytest.fixture
def two_milks(db):
    with active_user_profile_context(A):
        return [items.add("tasks", "أشتري حليب"), items.add("tasks", "أشتري حليب")]


def test_ambiguous_delete_asks_which_one(two_milks):
    model = ScriptedModel(tools_reply(call("list_update", list="tasks",
                                           match_text="حليب", delete=True)))
    state = _turn(model, "احذفي مهمة الحليب")
    assert state["pending_state"]["action"] == confirm.CHOOSE
    assert "١. أشتري حليب" in state["final_response"]
    assert len(model.seen) == 1


def test_first_then_yes_deletes_only_that_one(two_milks):
    asked = _turn(ScriptedModel(tools_reply(call("list_update", list="tasks",
                                                 match_text="حليب", delete=True))),
                  "احذفي مهمة الحليب")
    chosen = _turn(ScriptedModel(), "الأولى", asked["pending_state"])
    assert chosen["final_response"].startswith("متأكد إنك بدك تحذف")
    done = _turn(ScriptedModel(), "اه", chosen["pending_state"])
    assert done["pending_state"] is None
    with active_user_profile_context(A):
        left = [i["id"] for i in items.list_items("tasks")]
    assert len(left) == 1 and left[0] in two_milks


@pytest.mark.parametrize("said,count", [("كلهم", 2), ("2", 1), ("التانية", 1)])
def test_pick_reads_numbers_ordinals_and_all(said, count):
    cands = [{"id": "a", "text": "حليب"}, {"id": "b", "text": "حليب"}]
    assert len(confirm.pick(said, cands)) == count


def test_a_new_request_instead_of_a_choice_drops_the_question(two_milks):
    asked = _turn(ScriptedModel(tools_reply(call("list_update", list="tasks",
                                                 match_text="حليب", delete=True))),
                  "احذفي مهمة الحليب")
    model = ScriptedModel()
    state = _turn(model, "شو الطقس اليوم؟", asked["pending_state"])
    assert state["pending_state"] is None and len(model.seen) == 1
