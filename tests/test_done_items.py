"""Done items stay where they are with when they were done (owner, 30 Oct 2026): a list shows
the open ones and those done this past week; «فضّي اللي تمّ» hides the done ones at once;
«شو اشتريت هالشهر؟» answers from them, hidden or not; hiding by age writes nothing, so it is
no event and no email. In both languages."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from brain_fakes import A, brain_db  # noqa: F401

from app.blocks import events, items
from app.brain import lang, tools
from app.brain.ctx import TurnCtx
from app.utils.user_profiles import active_user_profile_context

NOW = datetime.now(timezone.utc)


@pytest.fixture
def shop(brain_db):  # noqa: F811
    with active_user_profile_context(A):
        items.add("shopping", "خبز")
        items.add("shopping", "رمان", done=True, done_at=NOW - timedelta(days=2))
        items.add("shopping", "حليب", done=True, done_at=NOW - timedelta(days=9))
        yield brain_db


def _run(name, language="ar", **args):
    with active_user_profile_context(A), lang.using(language):
        return tools.execute(name, args, TurnCtx(user_id="userA", message=args.pop("_said", "")))


def test_a_list_shows_the_open_ones_and_this_weeks_done(shop):
    with active_user_profile_context(A):
        shown = {r["text"] for r in items.list_items("shopping", visible=True)}
        everything = {r["text"] for r in items.list_items("shopping")}
    assert shown == {"خبز", "رمان"} and everything == {"خبز", "رمان", "حليب"}


def test_hiding_by_age_writes_nothing(shop):
    with active_user_profile_context(A):
        before = events.last_seq()
        items.list_items("shopping", visible=True)
        assert events.last_seq() == before


@pytest.mark.parametrize("language, said", [("ar", "قائمة التسوق"), ("en", "Shopping list")])
def test_clearing_the_done_hides_them_at_once_and_keeps_them(shop, language, said):
    out = _run("list_update", language, list="shopping", hide_done=True)
    assert out["ok"] and said in out["reply"]
    with active_user_profile_context(A):
        assert {r["text"] for r in items.list_items("shopping", visible=True)} == {"خبز"}
        assert len(items.list_items("shopping")) == 3                  # still there
        assert [e["op"] for e in events.since(0)][-1] == "hidden"


@pytest.mark.parametrize("language", ["ar", "en"])
def test_what_he_bought_this_month_comes_from_the_done_ones_hidden_or_not(shop, language):
    _run("list_update", language, list="shopping", hide_done=True)
    out = _run("recall", language, list="shopping", since=(NOW - timedelta(days=30)).isoformat())
    bought = {r["text"] for r in out["rows"] if r.get("done")}
    assert bought == {"رمان", "حليب"} and "خبز" not in {r["text"] for r in out["rows"]}


def test_the_apps_list_hides_the_old_done_ones_and_can_show_all(shop, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    from app.api.auth_handlers import make_token
    from app.api.server import create_app
    c = create_app(mongo_db=shop).test_client()
    h = {"Authorization": f"Bearer {make_token('user', user_id='userA')}"}
    done = c.get("/api/items?list=shopping&done=true", headers=h).get_json()["items"]
    assert [r["text"] for r in done] == ["رمان"] and done[0]["done_at"]
    everything = c.get("/api/items?list=shopping&done=true&all=1", headers=h).get_json()["items"]
    assert {r["text"] for r in everything} == {"رمان", "حليب"}
    r = c.post("/api/items/hide-done", headers=h, json={"list": "shopping"})
    assert r.status_code == 200 and r.get_json()["hidden"] == 2       # the old one too, marked now
    assert c.get("/api/items?list=shopping&done=true", headers=h).get_json()["items"] == []


def test_a_hidden_item_is_no_news_to_a_task():
    from app.brain import task_diff
    log = [{"row": "1", "op": "hidden", "list": "shopping", "label": "رمان",
            "before": {"hidden_at": None}, "after": {"hidden_at": NOW}}]
    assert task_diff.empty(task_diff.from_events(log))
