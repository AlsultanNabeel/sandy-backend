"""«اشتريت الحليب»: Sandy ticks the shopping item by its id (the model decides; these
check that what she asks for lands right)."""
from __future__ import annotations

from brain_fakes import A, ScriptedModel, brain_db, call, text_reply, tools_reply  # noqa: F401

from app.blocks import entries, items
from app.brain import context, loop
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


def test_she_is_told_to_tick_what_was_bought_and_sees_the_ids(brain_db):  # noqa: F811
    (milk,) = _shopping("حليب")
    model = ScriptedModel(text_reply("تمام"))
    _turn(model, "اشتريت الحليب")
    system = model.seen[0][0]["content"]
    assert "اشترى أو جاب" in system and f"#{milk}" in system


def test_bought_milk_ticks_milk(brain_db):  # noqa: F811
    milk, _ = _shopping("حليب", "بيض")
    _turn(ScriptedModel(tools_reply(call("list_update", id=milk, done=True)), text_reply("شطبته")),
          "اشتريت الحليب")
    assert _open() == ["بيض"]


def test_bread_and_eggs_both_go(brain_db):  # noqa: F811
    bread, eggs, _ = _shopping("خبز", "بيض", "شاي")
    _turn(ScriptedModel(tools_reply(call("list_update", id=bread, done=True),
                                    call("list_update", cid="c2", id=eggs, done=True)),
                        text_reply("تمام")), "جبت الخبز والبيض")
    assert _open() == ["شاي"]


def test_a_price_logs_the_expense_too(brain_db):  # noqa: F811
    (milk,) = _shopping("حليب")
    _turn(ScriptedModel(tools_reply(call("list_update", id=milk, done=True),
                                    call("remember", cid="c2", kind="expense", text="حليب",
                                         data={"amount": 20})),
                        text_reply("شطبته وسجّلت عشرين")), "اشتريت حليب بعشرين")
    assert _open() == []
    with active_user_profile_context(A):
        assert [e["data"]["amount"] for e in entries.list_entries("expense")] == [20]


def test_part_of_it_lowers_the_quantity(brain_db):  # noqa: F811
    (eggs,) = _shopping("بيض", qty=6, unit="حبة")
    _turn(ScriptedModel(tools_reply(call("list_update", id=eggs, qty=4)), text_reply("تمام")),
          "جبت ٢ بيض")
    with active_user_profile_context(A):
        row = items.get(eggs)
    assert row["done"] is False and row["data"] == {"qty": 4, "unit": "حبة"}


def test_something_not_on_the_list_changes_nothing(brain_db):  # noqa: F811
    _shopping("حليب")
    _turn(ScriptedModel(text_reply("حلو، استمتع فيها")), "اشتريت شوكولاتة")
    assert _open() == ["حليب"]
    assert "اللي مش بالقائمة ما" in context._RULES
