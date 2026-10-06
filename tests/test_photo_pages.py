"""The album past its first few hundred photos: every photo reachable in pages, a search
over all of them (it looked at the newest 500), and every album named."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import mongomock
import pytest


@pytest.fixture()
def album(monkeypatch):
    from app.api.server import create_app
    from app.api.auth_handlers import make_token

    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    db = mongomock.MongoClient().db
    c = create_app(mongo_db=db).test_client()
    from app.features import photo_album
    # The bytes store (GridFS) has no in-memory stand-in; listing never touches it.
    monkeypatch.setattr(photo_album, "_gridfs", object())
    h = {"Authorization": f"Bearer {make_token('user', user_id='u1')}"}
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def add(n, *, tags=(), caption=""):
        base = db["sandy_photos"].count_documents({})
        db["sandy_photos"].insert_many([
            {"_id": f"p{base + i:05d}", "chat_id": "u1", "name": f"صورة {base + i}",
             "ai_caption": caption, "tags": list(tags),
             "created_at": start + timedelta(minutes=base + i)} for i in range(n)])
    return c, h, add


def test_every_photo_comes_in_pages(album):
    c, h, add = album
    add(250)
    seen, cursor = [], None
    for _ in range(5):
        q = {"before": cursor} if cursor else {}
        body = c.get("/api/photos", query_string=q, headers=h).get_json()
        seen += [p["id"] for p in body["items"]]
        cursor = body.get("next")
        if not cursor:
            break
    assert len(seen) == 250 and len(set(seen)) == 250


def test_a_search_reaches_the_oldest_photo(album):
    c, h, add = album
    add(1, caption="البحر الميت مع العيلة")
    add(600)
    body = c.get("/api/photos", query_string={"q": "البحر"}, headers=h).get_json()
    assert [p["caption"] for p in body["items"]] == ["البحر الميت مع العيلة"]


def test_an_album_only_old_photos_have_is_still_listed(album):
    c, h, add = album
    add(1, tags=["عرس"])
    add(600)
    names = [a["name"] for a in c.get("/api/photos/albums", headers=h).get_json()["items"]]
    assert "عرس" in names
