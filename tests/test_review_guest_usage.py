"""Guest budget: finite, and closed when the database is not answering."""
import mongomock

from app.agent import guest_usage as gu


def _db():
    db = mongomock.MongoClient().db
    db.guest_usage.create_index([("jti", 1), ("chat_type", 1)], unique=True)
    return db


def test_budget_runs_out_then_pending():
    db = _db()
    got = [gu.check_and_increment("j1", "", "all", db)[0] for _ in range(5)]
    assert got == ["allow", "allow", "allow", "pending", "pending"]
    assert gu.get_usage_doc("j1", "all", db)["approval_state"] == "pending"


def test_budgets_are_per_guest():
    db = _db()
    for _ in range(3):
        gu.check_and_increment("j1", "", "all", db)
    assert gu.check_and_increment("j2", "", "all", db)[0] == "allow"


def test_database_error_fails_closed():
    class _Broken:
        def __getitem__(self, _name):
            raise RuntimeError("down")

    assert gu.check_and_increment("j1", "", "all", _Broken())[0] == "block"
