"""A bulk delete waits for his yes in a turn before, whatever the model decided (owner,
1 Nov 2026): «فضّيلي قائمة التسوق» was read as «clear the done ones» and asked nothing. The
tool itself holds a delete that empties a list (by `everything`, or by naming every open item
of it) or takes more than five rows in one turn (in one call or several), and deletes only on
the replay of his yes. «فضّي اللي تمّ» only hides, deletes nothing, and never asks. In both
languages."""
from __future__ import annotations

import pytest
from brain_fakes import A, brain_db  # noqa: F401

from app.blocks import items
from app.brain import lang, tools
from app.brain.ctx import TurnCtx
from app.utils.user_profiles import active_user_profile_context

LANGS = ["ar", "en"]


@pytest.fixture
def shop(brain_db):  # noqa: F811
    with active_user_profile_context(A):
        ids = [items.add("shopping", t) for t in ("حليب", "خبز")]
        yield ids


def _open(name="shopping"):
    with active_user_profile_context(A):
        return {r["text"] for r in items.list_items(name, done=False)}


def _do(tool, language, ctx=None, **args):
    ctx = ctx or TurnCtx(user_id="userA")
    with active_user_profile_context(A), lang.using(language):
        return tools.execute(tool, args, ctx)


@pytest.mark.parametrize("language", LANGS)
def test_emptying_a_list_waits_for_a_yes(shop, language):
    out = _do("list_delete", language, list="shopping", everything=True)
    assert out.get("needs_confirmation") and _open() == {"حليب", "خبز"}


@pytest.mark.parametrize("language", LANGS)
def test_naming_every_item_of_a_list_is_emptying_it_too(shop, language):
    out = _do("list_delete", language, list="shopping", ids=shop)
    assert out.get("needs_confirmation") and _open() == {"حليب", "خبز"}


@pytest.mark.parametrize("language", LANGS)
def test_more_than_five_in_one_turn_wait_even_in_small_calls(brain_db, language):  # noqa: F811
    with active_user_profile_context(A):
        ids = [items.add("tasks", f"مهمة {n}") for n in range(9)]
    ctx = TurnCtx(user_id="userA")
    assert _do("list_delete", language, ctx, list="tasks", ids=ids[:3])["ok"]
    out = _do("list_delete", language, ctx, list="tasks", ids=ids[3:6])
    assert out.get("needs_confirmation") and len(_open("tasks")) == 6


@pytest.mark.parametrize("language", LANGS)
def test_the_held_delete_goes_only_on_the_replay_of_his_yes(shop, language):
    asked = _do("list_delete", language, list="shopping", everything=True)
    ctx = TurnCtx(user_id="userA")
    ctx.confirmed, ctx.held_ids = True, asked["ids"]
    assert _do("list_delete", language, ctx, list="shopping", everything=True)["ok"]
    assert _open() == set()


@pytest.mark.parametrize("language", LANGS)
def test_one_named_item_goes_at_once(shop, language):
    with active_user_profile_context(A):
        items.add("shopping", "رز")
    assert _do("list_delete", language, list="shopping", match_text="حليب")["ok"]
    assert _open() == {"خبز", "رز"}


@pytest.mark.parametrize("language", LANGS)
def test_clearing_the_done_ones_never_asks_and_deletes_nothing(shop, language):
    with active_user_profile_context(A):
        for t in ("رمان", "موز", "تفاح", "عنب", "خوخ", "كرز", "تين"):
            items.update(items.add("shopping", t), done=True)
    out = _do("list_update", language, list="shopping", hide_done=True)
    assert out["ok"] and not out.get("needs_confirmation") and out["changed"] == 7
    with active_user_profile_context(A):
        assert len(items.list_items("shopping")) == 9                    # hidden, kept
