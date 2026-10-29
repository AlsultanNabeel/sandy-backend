"""The turn trace (`features/trace_store.py`): what one turn did, kept thirty days, its
words sealed with the memory key and opened for the owner's own turns only."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import mongomock
import pytest
from cryptography.fernet import Fernet

from app import db as appdb
from app.features import trace_store
from app.utils import ltm_crypto

OWNER = "owner1"


@pytest.fixture
def db(monkeypatch):
    d = mongomock.MongoClient().db
    appdb.configure(d)
    trace_store.init_trace_store(d)
    yield d
    appdb.reset()


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setattr(ltm_crypto, "_fernet", Fernet(Fernet.generate_key()))
    monkeypatch.setattr(ltm_crypto, "_init_attempted", True)


@pytest.fixture
def no_key(monkeypatch):
    monkeypatch.setattr(ltm_crypto, "_fernet", None)
    monkeypatch.setattr(ltm_crypto, "_init_attempted", True)


def _turn(user="u1", source="chat", request="ضيفي حليب", reply="ضفت حليب"):
    t = trace_store.Trace(user, source, thread_id="th1")
    t.add_model_call("azure", "gpt-4.1", tokens_in=1000, tokens_out=50, tokens_cached=200, ms=900)
    t.add_tool("list_add", {"text": "حليب"}, {"ok": True, "reply": "ضفت حليب"}, ms=12)
    return t, t.finish(request=request, reply=reply, routed_by="brain")


def test_a_turn_is_kept_with_every_field_and_its_words_sealed(db, key):
    _, tid = _turn()
    row = db[trace_store.COLLECTION].find_one({"_id": tid})
    assert row["user_id"] == "u1" and row["source"] == "chat" and row["thread_id"] == "th1"
    assert row["routed_by"] == "brain" and row["encrypted"] is True and row["error"] is None
    assert row["tokens_in"] == 1000 and row["tokens_out"] == 50 and row["cost_usd"] > 0
    assert row["skills"] == [] and row["task_id"] is None and row["ms_total"] >= 0
    assert row["model_calls"][0]["model"] == "gpt-4.1"
    for sealed in (row["request"], row["reply"], row["tools"][0]["args"], row["tools"][0]["result"]):
        assert sealed.startswith("enc:"), sealed
    assert "حليب" not in str(row)
    assert row["tools"][0]["name"] == "list_add" and row["tools"][0]["ok"] is True


def test_without_the_key_no_words_are_kept_but_the_numbers_are(db, no_key):
    _, tid = _turn()
    row = db[trace_store.COLLECTION].find_one({"_id": tid})
    assert row["encrypted"] is False
    assert row["request"] is None and row["reply"] is None
    assert row["tools"][0]["args"] is None and row["tools"][0]["result"] is None
    assert row["tokens_in"] == 1000 and row["tools"][0]["name"] == "list_add"
    assert "حليب" not in str(row)


def test_rows_go_by_themselves_after_thirty_days(db, key):
    _, tid = _turn()
    row = db[trace_store.COLLECTION].find_one({"_id": tid})
    assert row["expire_at"] - row["at"] == timedelta(days=30)
    ttl = [i for i in db[trace_store.COLLECTION].list_indexes() if i.get("expireAfterSeconds") == 0]
    assert ttl and list(ttl[0]["key"]) == ["expire_at"]


def test_the_owner_reads_the_words_of_his_own_turns_only(db, key):
    _, mine = _turn(user=OWNER)
    _, theirs = _turn(user="u2")
    own = trace_store.get_trace(OWNER, mine)
    assert own["request"] == "ضيفي حليب" and own["reply"] == "ضفت حليب"
    assert own["tools"][0]["args"] == {"text": "حليب"}
    other = trace_store.get_trace(OWNER, theirs)
    assert other["request"] is None and other["reply"] is None
    assert other["tools"][0]["args"] is None and other["tools"][0]["result"] is None
    assert other["tools"][0]["name"] == "list_add" and other["tokens_in"] == 1000


def test_the_list_never_carries_words(db, key):
    _turn(user=OWNER)
    _turn(user="u2", source="voice")
    rows = trace_store.list_traces(OWNER, limit=10)
    assert len(rows) == 2
    for r in rows:
        assert "request" not in r and "reply" not in r
        assert all("args" not in t and "result" not in t for t in r["tools"])
    assert [r["user_id"] for r in trace_store.list_traces(OWNER, user="u2")] == ["u2"]
    assert [r["source"] for r in trace_store.list_traces(OWNER, source="voice")] == ["voice"]


def test_a_failed_write_never_raises(db, key, monkeypatch):
    t = trace_store.Trace("u1", "chat")

    class Broken:
        def insert_one(self, *a, **k):
            raise RuntimeError("db down")
    monkeypatch.setattr(trace_store, "_collection", lambda user_id: Broken())
    assert t.finish(request="x", reply="y") is None


def test_the_current_trace_collects_model_calls_and_tools(db, key):
    t = trace_store.Trace("u1", "chat")
    trace_store.note_model_call("azure", "gpt-4.1", tokens_in=10, tokens_out=2)
    with trace_store.using(t):
        trace_store.note_model_call("azure", "gpt-4.1", tokens_in=10, tokens_out=2, ms=5)
        trace_store.note_tool("weather", {"city": "عمان"}, {"ok": True}, ms=3)
    trace_store.note_tool("weather", {}, {"ok": True})
    assert len(t.model_calls) == 1 and len(t.tools) == 1


def test_a_background_call_is_its_own_row_with_no_words(db, key):
    with trace_store.background("u1", "stm_summary"):
        trace_store.note_model_call("azure", "gpt-4.1", tokens_in=300, tokens_out=40)
    row = db[trace_store.COLLECTION].find_one({"source": "background"})
    assert row["user_id"] == "u1" and row["routed_by"] == "stm_summary"
    assert row["request"] is None and row["tokens_in"] == 300


def test_a_background_call_that_made_no_model_call_leaves_no_row(db, key):
    with trace_store.background("u1", "title"):
        pass
    assert db[trace_store.COLLECTION].count_documents({}) == 0


def test_costs_by_user_and_by_source(db, key):
    _turn(user=OWNER)
    _turn(user="u2")
    _turn(user="u2", source="voice")
    old = datetime.now(timezone.utc) - timedelta(days=40)
    db[trace_store.COLLECTION].insert_one({"_id": "old", "user_id": "u2", "at": old,
                                           "source": "chat", "cost_usd": 5.0,
                                           "tokens_in": 1, "tokens_out": 1})
    c = trace_store.costs(days=30)
    assert c["days"] == 30 and c["by_task"] == []
    by_user = {r["user_id"]: r for r in c["by_user"]}
    assert by_user["u2"]["turns"] == 2 and by_user[OWNER]["turns"] == 1
    assert by_user["u2"]["tokens_in"] == 2000
    assert round(c["total_usd"], 6) == round(sum(r["usd"] for r in c["by_user"]), 6)
    assert {r["source"]: r["turns"] for r in c["by_source"]} == {"chat": 2, "voice": 1}


def test_one_users_rows_are_written_under_that_user_only(db, key):
    _turn(user="u1")
    assert {r["user_id"] for r in db[trace_store.COLLECTION].find()} == {"u1"}


def test_reasoning_tokens_are_their_own_column_in_the_row_and_the_costs(db, key):
    # A reasoning model's thinking is billed as output; it is kept apart so it can be seen.
    t = trace_store.Trace(OWNER, "chat", thread_id="th1")
    t.add_model_call("azure", "gpt-6-luna", tokens_in=1000, tokens_out=300, tokens_reasoning=200)
    t.add_model_call("azure", "gpt-4.1", tokens_in=1000, tokens_out=50)
    t.finish(request="x", reply="y", routed_by="brain")
    row = db[trace_store.COLLECTION].find_one({"user_id": OWNER})
    assert row["tokens_reasoning"] == 200 and row["tokens_out"] == 350
    assert row["model_calls"][0]["tokens_reasoning"] == 200
    mine = next(u for u in trace_store.costs(days=1)["by_user"] if u["user_id"] == OWNER)
    assert mine["tokens_reasoning"] == 200
