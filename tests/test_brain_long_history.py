"""Answers over a long history: what she reads must be the period asked about, and a
total must be the whole total, not the part that fit in one read."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from brain_fakes import A, brain_db  # noqa: F401

from app.blocks import items
from app.brain import tools
from app.brain import when as W
from app.brain.ctx import TurnCtx
from app.utils import time as T
from app.utils.user_profiles import active_user_profile_context


@pytest.fixture
def tenant(brain_db):  # noqa: F811
    T._cache.clear()
    with active_user_profile_context(A):
        yield brain_db
    T._cache.clear()


def _run(name, **args):
    return tools.execute(name, args, TurnCtx(user_id="userA"))


def test_today_s_summary_sees_today_s_tasks_after_hundreds_of_old_ones(tenant):
    long_ago = datetime.now(timezone.utc) - timedelta(days=90)
    tenant["sandy_items"].insert_many([
        {"_id": f"old{i}", "user_id": "userA", "list": "tasks", "text": f"قديم {i}",
         "done": False, "created_at": long_ago + timedelta(minutes=i), "data": {}}
        for i in range(250)])
    items.add("tasks", "اتصل بالبنك")
    texts = [r.get("text") for r in _run("summarize", period="today")["rows"]]
    assert "اتصل بالبنك" in texts
    assert not any(t and t.startswith("قديم") for t in texts)


def _expenses(tenant, n, *, days_back=300):
    now = datetime.now(timezone.utc)
    tenant["sandy_entries"].insert_many([
        {"_id": f"e{i}", "user_id": "userA", "kind": "expense", "text": "قهوة",
         "data": {"amount": 1, "category": "food"},
         "at": now - timedelta(days=days_back * i / n, minutes=1)}
        for i in range(n)])


def test_a_year_of_expenses_is_totalled_whole(tenant):
    _expenses(tenant, 600)
    since = (datetime.now(timezone.utc) - timedelta(days=330)).date().isoformat()
    spent = _run("recall", kind="expense", since=since)["spending"]
    assert spent["total"] == 600 and spent["count"] == 600


def test_a_year_s_summary_totals_every_expense(tenant):
    start = W.period_range("year")[0]
    days_in = (datetime.now(timezone.utc) - start).days
    _expenses(tenant, 600, days_back=max(1, days_in - 1))
    spent = _run("summarize", period="year")["spending"]
    assert spent["total"] == 600 and spent["count"] == 600


def _open_rows(tenant, n):
    long_ago = datetime.now(timezone.utc) - timedelta(days=90)
    tenant["sandy_items"].insert_many([
        {"_id": f"o{i}", "user_id": "userA", "list": "shopping", "text": f"غرض رقم {i}",
         "done": False, "created_at": long_ago + timedelta(minutes=i), "data": {}}
        for i in range(n)])


def test_a_named_item_is_found_past_the_two_hundredth(tenant):
    _open_rows(tenant, 250)
    newest = items.add("shopping", "زيت زيتون")
    out = _run("list_update", list="shopping", match_text="زيت زيتون", done=True)
    assert out.get("ok") and items.get(newest)["done"]


def test_the_same_item_again_is_not_added_twice_in_a_long_list(tenant):
    _open_rows(tenant, 250)
    first = items.add("shopping", "زيت زيتون")
    _run("list_add", list="shopping", text="زيت زيتون", qty=2)
    same = [d for d in tenant["sandy_items"].find({"text": "زيت زيتون"})]
    assert len(same) == 1 and same[0]["_id"] == first
