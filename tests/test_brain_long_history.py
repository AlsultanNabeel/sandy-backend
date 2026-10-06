"""Answers over a long history: what she reads must be the period asked about, and a
total must be the whole total, not the part that fit in one read."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from brain_fakes import A, brain_db  # noqa: F401

from app.blocks import entries, items
from app.brain import tools
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
