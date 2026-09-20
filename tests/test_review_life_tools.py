"""Life tools: goal parts, shopping input shapes, no double expense."""
import mongomock

from app import db as appdb
from app.utils.user_profiles import active_user_profile_context

_P = {"user_id": "u1", "chat_id": "u1", "relation": "user", "permissions": "all"}


def _db():
    d = mongomock.MongoClient().db
    appdb.configure(d)
    return d


def test_setting_books_keeps_the_page_goal():
    from app.features.reading_store import set_reading_goal
    _db()
    try:
        with active_user_profile_context(_P):
            set_reading_goal(pages_year=5000)
            r = set_reading_goal(books_year=24)
        assert (r["books_year"], r["pages_year"]) == (24, 5000)
    finally:
        appdb.reset()


def test_a_single_string_item_is_one_item():
    from app.agent.tools.schemas.life_tools.shopping import shopping_add
    from app.features.shopping_store import list_items
    _db()
    try:
        with active_user_profile_context(_P):
            shopping_add({"items": "حليب"}, None)
            assert [i["text"] for i in list_items()] == ["حليب"]
    finally:
        appdb.reset()


def test_rebuying_does_not_add_the_expense_twice():
    from app.features import shopping_store
    d = _db()
    try:
        with active_user_profile_context(_P):
            shopping_store.add_item("خبز")
            item = shopping_store.list_items()[0]
            first = shopping_store.check_item_by_id(item["id"], price=5)
            second = shopping_store.check_item_by_id(item["id"], price=5)
        assert first["expense_added"] and not second["expense_added"]
        assert d["sandy_expenses"].count_documents({}) == 1
    finally:
        appdb.reset()


def test_books_list_and_overview_from_one_sessions_read():
    """list_books counts notes/quotes in the database; reading_overview gives the
    same numbers reading_stats + goal_progress would, from one sessions read."""
    from datetime import datetime, timedelta, timezone

    from app.features import reading_store as rs
    d = _db()
    try:
        with active_user_profile_context(_P):
            rs.add_book("كتاب", total_pages=300)
            rs.add_note("كتاب", "ملاحظة")
            rs.add_quote("كتاب", "اقتباس", page=3)
            rs.add_quote("كتاب", "اقتباس تاني", page=4)
            rs.set_reading_goal(pages_year=1000)
            now = datetime.now(timezone.utc)
            book_id = rs.list_books()[0]["id"]
            for days_ago, pages in ((0, 20), (1, 10), (100, 5)):
                end = now - timedelta(days=days_ago)
                d["sandy_reading_sessions"].insert_one({
                    "_id": f"s{days_ago}", "user_id": "u1", "book_id": book_id,
                    "state": "done", "started_at": end - timedelta(minutes=30),
                    "ended_at": end, "start_page": 0, "end_page": pages,
                    "paused_total_sec": 0,
                })
            [book] = rs.list_books()
            assert (book["notes_count"], book["quotes_count"]) == (1, 2)
            stats, goal = rs.reading_overview(days=30)
            assert stats == rs.reading_stats(days=30)
            assert goal == rs.goal_progress()
            assert (stats["sessions"], stats["pages"], stats["streak_days"]) == (2, 30, 2)
            assert goal["pages_year"] == 1000
    finally:
        appdb.reset()
