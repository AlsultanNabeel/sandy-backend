"""«اشتريت الحليب»: what was bought comes off the shopping list, by the code."""
from __future__ import annotations

from brain_fakes import A, ScriptedModel, brain_db, call, text_reply, tools_reply  # noqa: F401

from app.blocks import entries, items
from app.brain import loop
from app.utils.user_profiles import active_user_profile_context


def _turn(model, message):
    with active_user_profile_context(A):
        return loop.run_turn(message, user_id="userA", chat_id="userA", source="web", complete=model)


def _shopping(*names, **data):
    with active_user_profile_context(A):
        return [items.add("shopping", n, data or None) for n in names]


def _open():
    with active_user_profile_context(A):
        return sorted(i["text"] for i in items.list_items("shopping", done=False))


def test_bought_milk_ticks_milk(brain_db):  # noqa: F811
    _shopping("حليب", "بيض")
    model = ScriptedModel(text_reply("شطبته"))
    _turn(model, "اشتريت الحليب")
    assert _open() == ["بيض"]
    assert "«حليب» خلص" in model.seen[0][0]["content"]


def test_bread_and_eggs_both_go(brain_db):  # noqa: F811
    _shopping("خبز", "بيض", "شاي")
    _turn(ScriptedModel(text_reply("تمام")), "جبت الخبز والبيض")
    assert _open() == ["شاي"]


def test_a_price_logs_the_expense_too(brain_db):  # noqa: F811
    _shopping("حليب")
    model = ScriptedModel(tools_reply(call("remember", kind="expense", text="حليب",
                                           data={"amount": 20})),
                          text_reply("شطبته وسجّلت عشرين"))
    _turn(model, "اشتريت حليب بعشرين")
    assert _open() == []
    with active_user_profile_context(A):
        assert [e["data"]["amount"] for e in entries.list_entries("expense")] == [20]


def test_part_of_it_lowers_the_quantity(brain_db):  # noqa: F811
    (eggs,) = _shopping("بيض", qty=6)
    _turn(ScriptedModel(text_reply("تمام")), "جبت ٢ بيض")
    with active_user_profile_context(A):
        row = items.get(eggs)
    assert row["done"] is False and row["data"]["qty"] == 4


def test_something_not_on_the_list_is_not_added(brain_db):  # noqa: F811
    _shopping("حليب")
    model = ScriptedModel(tools_reply(call("list_add", list="shopping", text="شوكولاتة")),
                          text_reply("تمام"))
    _turn(model, "اشتريت شوكولاتة")
    assert _open() == ["حليب"]
