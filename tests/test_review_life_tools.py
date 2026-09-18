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
