"""The four failures of the first live test of the new agent (2026-09-30)."""
from __future__ import annotations

import pytest
from brain_fakes import A, ScriptedModel, brain_db, call, text_reply, tools_reply  # noqa: F401

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
    assert len(model.seen) == 2  # the rest of the request still runs, then the question


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


def test_a_new_request_instead_of_a_choice_is_answered_and_asked_once_more(two_milks):
    asked = _turn(ScriptedModel(tools_reply(call("list_update", list="tasks",
                                                 match_text="حليب", delete=True))),
                  "احذفي مهمة الحليب")
    model = ScriptedModel(text_reply("مشمس"))
    state = _turn(model, "شو الطقس اليوم؟", asked["pending_state"])
    assert len(model.seen) == 1 and state["final_response"].startswith("مشمس\nلقيت أكتر من وحدة")
    again = _turn(ScriptedModel(text_reply("تمام")), "احكيلي نكتة", state["pending_state"])
    assert again["pending_state"] is None and again["final_response"] == "تمام"


@pytest.mark.parametrize("said,count", [("الأولى والتالتة", 2), ("اتنين", 1), ("الاتنين", 3),
                                        ("١ و٣", 2)])
def test_pick_reads_several_and_a_bare_number_is_that_one(said, count):
    cands = [{"id": "a", "text": "حليب"}, {"id": "b", "text": "حليب"}, {"id": "c", "text": "حليب"}]
    assert len(confirm.pick(said, cands)) == count
    if said == "اتنين":
        assert confirm.pick(said, cands) == ["b"]


# Second live test: the model sent kind="tasks" (a list) and got nothing back.
@pytest.mark.parametrize("args", [{"kind": "tasks"}, {"list": "tasks"}, {"kind": "مهام"},
                                  {"list": "المهام"}])
def test_recall_finds_a_list_whichever_slot_names_it(db, args):
    with active_user_profile_context(A):
        items.add("tasks", "تقرير المشروع")
    assert [r["text"] for r in _run("recall", **args)["rows"]] == ["تقرير المشروع"]


def test_recall_finds_a_log_kind_sent_as_a_list(db):
    with active_user_profile_context(A):
        entries.add("expense", "غدا", {"amount": 50.0}, embed=False)
    assert _run("recall", list="expense")["rows"][0]["kind"] == "expense"


# Third live test: «عالخمسة» at 13:30 became 14:00, and «كمان نص» counted from now.
@pytest.mark.parametrize("said,expected", [
    ("عال٥", "17:00"), ("الساعة ٥", "17:00"), ("الساعة 5 الصبح", "05:00 +1"),
    ("الساعة ٥ ونص", "17:30"), ("بكرا الساعة ٨", "08:00 +1"), ("الساعة 9 المسا", "21:00"),
    ("عالساعة 14:45", "14:45"), ("بعد 5 دقايق", None),
])
def test_a_spoken_clock_time_is_the_next_such_moment(said, expected):
    from datetime import datetime, timedelta
    from app.brain import when as W
    from app.utils.time import USER_TZ
    now = datetime(2026, 9, 30, 13, 30, tzinfo=USER_TZ)
    got = W._clock(said, now)
    if expected is None:
        assert got is None
        return
    local = got.astimezone(USER_TZ)
    hhmm, _, plus = expected.partition(" +")
    assert local.strftime("%H:%M") == hhmm
    assert local.date() == (now + timedelta(days=int(plus or 0))).date()


def test_relative_times_are_counted_by_the_code(db):
    from datetime import timedelta
    from app.blocks import schedules
    from app.brain import when as W
    before = W.now_utc()
    out = _run("schedule", kind="reminder", text="اشرب مي", in_minutes=30)
    with active_user_profile_context(A):
        row = schedules.get(out["id"])
    at = W.aware_utc(row["fire_at"])
    assert timedelta(minutes=29) < at - before < timedelta(minutes=31)
    # «أجّليه كمان نص ساعة»: thirty more minutes from its own time, not from now.
    _run("schedule_update", id=out["id"], shift_minutes=30)
    with active_user_profile_context(A):
        moved = W.aware_utc(schedules.get(out["id"])["fire_at"])
    assert moved - at == timedelta(minutes=30)
