"""Long lists: every row reachable in pages, the done list newest first, and every list's
name (they used to come from the 500 oldest rows)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from brain_fakes import brain_db  # noqa: F401 — fixture


@pytest.fixture()
def c(monkeypatch, brain_db):  # noqa: F811
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    from app.api.server import create_app
    return create_app(mongo_db=brain_db).test_client(), brain_db


def _h():
    from app.api.auth_handlers import make_token
    return {"Authorization": f"Bearer {make_token('user', user_id='userA')}"}


def _rows(db, n, *, list_name="tasks", done=False, start=None):
    start = start or datetime(2026, 1, 1, tzinfo=timezone.utc)
    db["sandy_items"].insert_many([
        {"_id": f"{list_name}-{done}-{i:04d}", "user_id": "userA", "list": list_name,
         "text": f"{list_name} {i}", "done": done, "data": {},
         "created_at": start + timedelta(minutes=i)} for i in range(n)])


def test_an_open_list_past_one_page_comes_whole_in_pages(c):
    client, db = c
    _rows(db, 230)
    seen, cursor, pages = [], None, 0
    while True:
        q = {"list": "tasks", "done": "false", **({"cursor": cursor} if cursor else {})}
        body = client.get("/api/items", query_string=q, headers=_h()).get_json()
        seen += [r["id"] for r in body["items"]]
        pages += 1
        cursor = body.get("next")
        if not cursor:
            break
    assert pages == 3 and len(seen) == 230 and len(set(seen)) == 230
    assert seen == sorted(seen), "a list reads oldest first"


def test_the_done_list_starts_with_the_newest(c):
    client, db = c
    _rows(db, 120, done=True)
    body = client.get("/api/items", query_string={"list": "tasks", "done": "true"},
                      headers=_h()).get_json()
    assert body["items"][0]["text"] == "tasks 119"


def test_every_list_name_is_known_however_old_the_rest(c):
    client, db = c
    _rows(db, 520)
    _rows(db, 1, list_name="project:بيت", start=datetime(2026, 9, 1, tzinfo=timezone.utc))
    body = client.get("/api/items/lists", headers=_h()).get_json()
    assert set(body["lists"]) == {"tasks", "project:بيت"}
