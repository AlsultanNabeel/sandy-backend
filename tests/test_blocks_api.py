"""/api/entries, /api/items, /api/schedules, /api/kinds, /api/summary (rebuild phase 3)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import pytest
from brain_fakes import brain_db, text_reply  # noqa: F401 — fixture

from app.blocks import entries, items, schedules
from app.blocks.kinds import KINDS
from app.utils.time import USER_TZ
from app.utils.user_profiles import active_user_profile_context


@pytest.fixture()
def c(monkeypatch, brain_db):  # noqa: F811
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    from app.api.server import create_app
    from app.features import usage_store
    monkeypatch.setattr(usage_store, "check_and_record", lambda *a, **k: None)
    app = create_app(mongo_db=brain_db)
    return app.test_client()


def _h(uid="userA", role="user"):
    from app.api.auth_handlers import make_token
    return {"Authorization": f"Bearer {make_token(role, user_id=uid)}"}


def _iso(days=1, hour=10):
    return (datetime.now(USER_TZ) + timedelta(days=days)).replace(
        hour=hour, minute=0, second=0, microsecond=0).isoformat()


def _bad(r, code, status=400):
    body = r.get_json()
    assert r.status_code == status, body
    assert body["error"] == code and body["message"].strip(), body


ROUTES = [("GET", "/api/entries"), ("POST", "/api/entries"),
          ("PATCH", "/api/entries/x"), ("DELETE", "/api/entries/x"),
          ("GET", "/api/items"), ("POST", "/api/items"),
          ("PATCH", "/api/items/x"), ("DELETE", "/api/items/x"),
          ("GET", "/api/schedules"), ("POST", "/api/schedules"),
          ("PATCH", "/api/schedules/x"), ("DELETE", "/api/schedules/x"),
          ("POST", "/api/schedules/x/snooze"),
          ("GET", "/api/kinds"), ("POST", "/api/summary")]


@pytest.mark.parametrize("method, path", ROUTES)
def test_every_route_needs_a_token(c, method, path):
    assert c.open(path, method=method, json={}).status_code == 401


@pytest.mark.parametrize("method, path", [r for r in ROUTES if r[1] != "/api/kinds"])
def test_a_guest_is_refused_the_tenant_routes(c, method, path):
    assert c.open(path, method=method, json={}, headers=_h(None, "guest")).status_code == 403


# ── kinds ────────────────────────────────────────────────────────────────────

def test_kinds_is_the_kinds_table(c):
    rows = c.get("/api/kinds", headers=_h()).get_json()["kinds"]
    assert [(r["block"], r["name"]) for r in rows] == [(k.block, k.name) for k in KINDS]
    expense = next(r for r in rows if r["name"] == "expense")
    assert expense["labels"] == {"ar": "مصروف", "en": "Expense"}
    assert expense["icon"] == "creditcard" and expense["fields"]["amount"] == "number"
    assert next(r for r in rows if r["name"] == "project:")["prefix"] is True
    fact = next(r for r in rows if r["name"] == "fact")
    assert fact["fields"]["last_seen"] == "datetime" and fact["fields"]["count"] == "int"


# ── entries ──────────────────────────────────────────────────────────────────

def test_entries_crud(c):
    r = c.post("/api/entries", json={"kind": "expense", "text": " قهوة ",
                                     "data": {"amount": 3.5}}, headers=_h())
    assert r.status_code == 200
    item = r.get_json()["item"]
    assert item["text"] == "قهوة" and item["data"] == {"amount": 3.5}
    assert item["source"] == "app" and "user_id" not in item and "embedding" not in item
    eid = item["id"]
    r = c.patch(f"/api/entries/{eid}", json={"text": "شاي", "data": {"amount": 2}}, headers=_h())
    assert r.get_json()["item"]["text"] == "شاي" and r.get_json()["item"]["data"]["amount"] == 2
    assert c.delete(f"/api/entries/{eid}", headers=_h()).get_json()["ok"] is True
    _bad(c.delete(f"/api/entries/{eid}", headers=_h()), "not_found", 404)
    _bad(c.patch(f"/api/entries/{eid}", json={"text": "x"}, headers=_h()), "not_found", 404)


def test_entries_filters(c):
    old = (datetime.now(USER_TZ) - timedelta(days=10)).isoformat()
    c.post("/api/entries", json={"kind": "expense", "text": "بنزين", "at": old}, headers=_h())
    c.post("/api/entries", json={"kind": "expense", "text": "غدا"}, headers=_h())
    c.post("/api/entries", json={"kind": "journal", "text": "يوم حلو"}, headers=_h())

    def texts(qs):
        return {r["text"] for r in c.get(f"/api/entries{qs}", headers=_h()).get_json()["items"]}

    assert texts("") == {"بنزين", "غدا", "يوم حلو"}
    assert texts("?kind=expense") == {"بنزين", "غدا"}
    since = (datetime.now(USER_TZ) - timedelta(days=1)).date().isoformat()
    assert texts(f"?since={since}") == {"غدا", "يوم حلو"}
    until = (datetime.now(USER_TZ) - timedelta(days=5)).date().isoformat()
    assert texts(f"?until={until}") == {"بنزين"}
    assert texts("?q=غدا") == {"غدا"}
    assert len(c.get("/api/entries?limit=1", headers=_h()).get_json()["items"]) == 1


@pytest.mark.parametrize("body, code", [
    ({"kind": "expense"}, "text_required"),
    ({"kind": "expense", "text": "   "}, "text_required"),
    ({"kind": "expense", "text": 5}, "text_required"),
    ({"kind": "expense", "text": "x" * 2001}, "text_too_long"),
    ({"kind": "nope", "text": "x"}, "invalid_kind"),
    ({"kind": "expense", "text": "x", "data": {"colour": "red"}}, "invalid_kind"),
    ({"kind": "expense", "text": "x", "data": {"amount": "lots"}}, "invalid_kind"),
    ({"kind": "expense", "text": "x", "data": {"note": "n" * 9000}}, "data_too_big"),
    ({"kind": "expense", "text": "x", "at": "yesterday-ish"}, "invalid_date"),
])
def test_entries_validation(c, body, code):
    _bad(c.post("/api/entries", json=body, headers=_h()), code)


def test_entries_query_validation_and_body_shape(c):
    _bad(c.get("/api/entries?limit=abc", headers=_h()), "invalid_limit")
    _bad(c.get("/api/entries?limit=0", headers=_h()), "invalid_limit")
    _bad(c.get("/api/entries?since=soon", headers=_h()), "invalid_date")
    _bad(c.post("/api/entries", data="not json", headers=_h()), "invalid_body")
    _bad(c.post("/api/entries", json=["a"], headers=_h()), "invalid_body")


def test_entry_datetime_fields_are_read_from_iso(c):
    r = c.post("/api/entries", json={"kind": "fact", "text": "x",
                                     "data": {"last_seen": "2026-01-02T03:04:05+00:00"}},
               headers=_h())
    assert r.get_json()["item"]["data"]["last_seen"].startswith("2026-01-02")
    with active_user_profile_context({"chat_id": "userA"}):
        assert isinstance(entries.get(r.get_json()["id"])["data"]["last_seen"], datetime)


def test_encrypted_entry_is_shown_decrypted_and_resealed_on_edit(c, monkeypatch):
    from cryptography.fernet import Fernet

    from app.utils import ltm_crypto
    monkeypatch.setattr(ltm_crypto, "_fernet", Fernet(Fernet.generate_key()))
    monkeypatch.setattr(ltm_crypto, "_init_attempted", True)
    embedded = []
    monkeypatch.setattr(entries, "embed_text", lambda t: embedded.append(t) or [1.0])
    with active_user_profile_context({"chat_id": "userA"}):
        eid = entries.add("mood", ltm_crypto.encrypt_field("زعلان"),
                          {"mood": "sad", "encrypted": True}, embed=False)
    assert c.get("/api/entries", headers=_h()).get_json()["items"][0]["text"] == "زعلان"
    r = c.patch(f"/api/entries/{eid}", json={"text": "أحسن"}, headers=_h())
    assert r.get_json()["item"]["text"] == "أحسن"
    with active_user_profile_context({"chat_id": "userA"}):
        raw = entries.get(eid)
    assert raw["text"] != "أحسن" and ltm_crypto.decrypt_field(raw["text"]) == "أحسن"
    assert embedded == []


# ── items ────────────────────────────────────────────────────────────────────

def test_items_crud_and_filters(c):
    milk = c.post("/api/items", json={"list": "shopping", "text": "حليب",
                                      "data": {"qty": 2}}, headers=_h()).get_json()["id"]
    c.post("/api/items", json={"list": "shopping", "text": "خبز", "done": True}, headers=_h())
    c.post("/api/items", json={"list": "tasks", "text": "اتصل بالبنك",
                               "due": _iso(), "priority": "high"}, headers=_h())
    c.post("/api/items", json={"list": "project:بيت", "text": "دهان"}, headers=_h())

    def texts(qs):
        return [r["text"] for r in c.get(f"/api/items{qs}", headers=_h()).get_json()["items"]]

    assert texts("?list=shopping") == ["حليب", "خبز"]
    assert texts("?list=shopping&done=false") == ["حليب"]
    assert texts("?done=true") == ["خبز"]
    assert texts("?q=بنك") == ["اتصل بالبنك"]
    assert texts("?list=project:بيت") == ["دهان"]
    assert len(texts("?limit=2")) == 2
    _bad(c.get("/api/items?done=maybe", headers=_h()), "invalid_done")

    r = c.patch(f"/api/items/{milk}", json={"done": True, "due": _iso()}, headers=_h())
    item = r.get_json()["item"]
    assert item["done"] is True and item["done_at"] and item["due"]
    r = c.patch(f"/api/items/{milk}", json={"due": None}, headers=_h())
    assert r.get_json()["item"]["due"] is None
    _bad(c.patch(f"/api/items/{milk}", json={"text": ""}, headers=_h()), "text_required")
    assert c.delete(f"/api/items/{milk}", headers=_h()).get_json()["ok"] is True
    _bad(c.delete(f"/api/items/{milk}", headers=_h()), "not_found", 404)


@pytest.mark.parametrize("body, code", [
    ({"list": "shopping"}, "text_required"),
    ({"list": "nope", "text": "x"}, "invalid_kind"),
    ({"list": "project:", "text": "x"}, "invalid_kind"),
    ({"list": "shopping", "text": "x", "due": "tomorrowish"}, "invalid_date"),
    ({"list": "shopping", "text": "x", "priority": "p" * 2001}, "text_too_long"),
])
def test_items_validation(c, body, code):
    _bad(c.post("/api/items", json=body, headers=_h()), code)


# ── schedules ────────────────────────────────────────────────────────────────

def test_schedules_crud_and_filters(c):
    r = c.post("/api/schedules", json={"kind": "reminder", "text": "دوا",
                                       "fire_at": _iso(1), "recurrence": "daily"}, headers=_h())
    sid = r.get_json()["id"]
    assert r.get_json()["item"]["recurrence"] == "FREQ=DAILY"
    assert r.get_json()["item"]["status"] == "pending"
    c.post("/api/schedules", json={"kind": "reminder", "text": "موعد", "fire_at": _iso(5),
                                   "recurrence": "FREQ=WEEKLY;BYDAY=MO"}, headers=_h())
    c.post("/api/schedules", json={"kind": "daily_nudge", "text": "صباح", "fire_at": _iso(2)},
           headers=_h())

    def texts(qs):
        return [r["text"] for r in c.get(f"/api/schedules{qs}", headers=_h()).get_json()["items"]]

    assert texts("") == ["دوا", "صباح", "موعد"]
    assert texts("?kind=reminder") == ["دوا", "موعد"]
    assert texts(f"?from={quote(_iso(3))}") == ["موعد"]
    assert texts(f"?to={quote(_iso(3))}") == ["دوا", "صباح"]
    assert texts("?status=pending&limit=1") == ["دوا"]
    _bad(c.get("/api/schedules?status=done", headers=_h()), "invalid_status")

    r = c.patch(f"/api/schedules/{sid}", json={"text": "الدوا", "fire_at": _iso(3)}, headers=_h())
    assert r.get_json()["item"]["text"] == "الدوا"
    assert c.patch(f"/api/schedules/{sid}", json={"status": "cancelled"},
                   headers=_h()).get_json()["item"]["status"] == "cancelled"
    assert texts("?status=cancelled") == ["الدوا"]
    _bad(c.patch(f"/api/schedules/{sid}", json={"status": "sent"}, headers=_h()), "invalid_status")
    assert c.delete(f"/api/schedules/{sid}", headers=_h()).get_json()["ok"] is True
    _bad(c.delete(f"/api/schedules/{sid}", headers=_h()), "not_found", 404)


def _rang(c, sid, brain_db):  # noqa: F811
    now = datetime.now(timezone.utc).replace(microsecond=0)
    brain_db["sandy_schedules"].update_one({"_id": sid}, {"$set": {"fired_at": now}})
    return now


def test_snoozing_a_one_off_that_rang_puts_it_back(c, brain_db):  # noqa: F811
    sid = c.post("/api/schedules", json={"kind": "reminder", "text": "المي", "fire_at": _iso(1)},
                 headers=_h()).get_json()["id"]
    brain_db["sandy_schedules"].update_one({"_id": sid}, {"$set": {"status": "sent"}})
    now = _rang(c, sid, brain_db)
    r = c.post(f"/api/schedules/{sid}/snooze", json={"minutes": 10}, headers=_h())
    row = r.get_json()["item"]
    assert r.status_code == 200 and row["id"] == sid and row["status"] == "pending"
    at = datetime.fromisoformat(row["fire_at"])
    assert now + timedelta(minutes=9) < at < now + timedelta(minutes=11)
    assert [x["id"] for x in c.get("/api/schedules?status=pending", headers=_h()).get_json()["items"]] == [sid]


def test_snoozing_a_repeat_rings_once_more_and_keeps_the_series(c, brain_db):  # noqa: F811
    first = _iso(1, hour=8)
    sid = c.post("/api/schedules", json={"kind": "reminder", "text": "الرياضة", "fire_at": first,
                                         "recurrence": "daily", "payload": {"important": True}},
                 headers=_h()).get_json()["id"]
    _rang(c, sid, brain_db)
    row = c.post(f"/api/schedules/{sid}/snooze", json={"minutes": 10}, headers=_h()).get_json()["item"]
    assert row["id"] != sid and row["recurrence"] == "" and row["payload"] == {"important": True}
    series = c.get("/api/schedules?status=pending", headers=_h()).get_json()["items"]
    assert next(x for x in series if x["id"] == sid)["fire_at"] == first


@pytest.mark.parametrize("body", [{}, {"minutes": 0}, {"minutes": "10"}, {"minutes": 1441}])
def test_a_snooze_needs_its_minutes(c, body):
    sid = c.post("/api/schedules", json={"kind": "reminder", "text": "x", "fire_at": _iso(1)},
                 headers=_h()).get_json()["id"]
    _bad(c.post(f"/api/schedules/{sid}/snooze", json=body, headers=_h()), "invalid_minutes")


def test_a_snooze_of_what_is_gone(c):
    _bad(c.post("/api/schedules/nope/snooze", json={"minutes": 5}, headers=_h()), "not_found", 404)
    sid = c.post("/api/schedules", json={"kind": "reminder", "text": "x", "fire_at": _iso(1)},
                 headers=_h()).get_json()["id"]
    c.patch(f"/api/schedules/{sid}", json={"status": "cancelled"}, headers=_h())
    _bad(c.post(f"/api/schedules/{sid}/snooze", json={"minutes": 5}, headers=_h()), "not_found", 404)


@pytest.mark.parametrize("body, code", [
    ({"kind": "reminder", "text": "x"}, "fire_at_required"),
    ({"kind": "reminder", "text": "x", "fire_at": "2020-01-01T10:00:00+00:00"}, "fire_at_in_past"),
    ({"kind": "reminder", "text": "x", "fire_at": "later"}, "invalid_date"),
    ({"kind": "reminder", "text": "x", "fire_at": "FUTURE", "recurrence": "sometimes"},
     "invalid_recurrence"),
    ({"kind": "reminder", "text": "x", "fire_at": "FUTURE", "recurrence": "FREQ=NEVER"},
     "invalid_recurrence"),
    ({"kind": "alarm", "text": "x", "fire_at": "FUTURE"}, "invalid_kind"),
    ({"kind": "scene", "text": "x", "fire_at": "FUTURE", "payload": {"tries": "2"}},
     "invalid_kind"),
    ({"kind": "reminder", "fire_at": "FUTURE"}, "text_required"),
])
def test_schedules_validation(c, body, code):
    body = {k: (_iso() if v == "FUTURE" else v) for k, v in body.items()}
    _bad(c.post("/api/schedules", json=body, headers=_h()), code)


def test_a_future_message_is_sealed_at_rest_and_readable_by_its_owner(c, monkeypatch):
    from cryptography.fernet import Fernet

    from app.utils import ltm_crypto
    monkeypatch.setattr(ltm_crypto, "_fernet", Fernet(Fernet.generate_key()))
    monkeypatch.setattr(ltm_crypto, "_init_attempted", True)
    r = c.post("/api/schedules", json={"kind": "message_to_future_self", "text": "سر",
                                       "fire_at": _iso(30)}, headers=_h())
    assert r.get_json()["item"]["text"] == "سر"
    with active_user_profile_context({"chat_id": "userA"}):
        raw = schedules.get(r.get_json()["id"])
    assert raw["text"] != "سر" and raw["payload"]["encrypted"] is True
    assert c.get("/api/schedules", headers=_h()).get_json()["items"][0]["text"] == "سر"


# ── tenant isolation ─────────────────────────────────────────────────────────

def test_a_tenant_cannot_see_or_touch_another_tenants_rows(c):
    eid = c.post("/api/entries", json={"kind": "note", "text": "سر أ"}, headers=_h()).get_json()["id"]
    iid = c.post("/api/items", json={"list": "tasks", "text": "مهمة أ"}, headers=_h()).get_json()["id"]
    sid = c.post("/api/schedules", json={"kind": "reminder", "text": "تذكير أ",
                                         "fire_at": _iso()}, headers=_h()).get_json()["id"]
    for path in ("/api/entries", "/api/items", "/api/schedules"):
        assert c.get(path, headers=_h("userB")).get_json()["items"] == []
    for path, row in (("/api/entries", eid), ("/api/items", iid), ("/api/schedules", sid)):
        _bad(c.patch(f"{path}/{row}", json={"text": "ب"}, headers=_h("userB")), "not_found", 404)
        _bad(c.delete(f"{path}/{row}", headers=_h("userB")), "not_found", 404)
    assert [r["text"] for r in c.get("/api/entries", headers=_h()).get_json()["items"]] == ["سر أ"]
    assert [r["text"] for r in c.get("/api/items", headers=_h()).get_json()["items"]] == ["مهمة أ"]
    assert len(c.get("/api/schedules", headers=_h()).get_json()["items"]) == 1


def test_a_tenant_field_in_the_body_is_ignored(c):
    c.post("/api/entries", json={"kind": "note", "text": "x", "user_id": "userB"}, headers=_h())
    assert c.get("/api/entries", headers=_h("userB")).get_json()["items"] == []


# ── summary ──────────────────────────────────────────────────────────────────

def test_summary_uses_the_brain_summarize_rows_and_one_model_call(c, monkeypatch):
    from app.brain import model
    seen = []

    def fake(messages, tools, on_text=None):
        seen.append((messages, tools))
        return text_reply("صرفت على القهوة اليوم.")

    monkeypatch.setattr(model, "complete", fake)
    c.post("/api/entries", json={"kind": "expense", "text": "قهوة", "data": {"amount": 3}},
           headers=_h())
    r = c.post("/api/summary", json={"period": "today"}, headers=_h())
    assert r.status_code == 200
    assert r.get_json() == {"ok": True, "text": "صرفت على القهوة اليوم.", "count": 1}
    (messages, tools), = seen
    assert tools == [] and "قهوة" in messages[-1]["content"]


def test_summary_with_nothing_recorded_costs_no_model_call(c, monkeypatch):
    from app.brain import model, summary
    monkeypatch.setattr(model, "complete", lambda *a, **k: pytest.fail("model called"))
    r = c.post("/api/summary", json={"period": "week", "focus": "expense"}, headers=_h())
    assert r.get_json()["text"] == summary.EMPTY_REPLY


def test_summary_validation_failure_and_metering(c, monkeypatch):
    from app.brain import model
    from app.features import usage_store
    _bad(c.post("/api/summary", json={"period": "decade"}, headers=_h()), "invalid_period")
    c.post("/api/entries", json={"kind": "note", "text": "x"}, headers=_h())
    monkeypatch.setattr(model, "complete", lambda *a, **k: None)
    _bad(c.post("/api/summary", json={"period": "today"}, headers=_h()), "summary_failed", 503)
    monkeypatch.setattr(usage_store, "check_and_record", lambda *a, **k: "rate_limited")
    r = c.post("/api/summary", json={"period": "today"}, headers=_h())
    assert r.status_code == 429 and r.get_json()["error"] == "rate_limited"


def test_items_store_is_untouched_by_a_refused_write(c):
    c.post("/api/items", json={"list": "nope", "text": "x"}, headers=_h())
    with active_user_profile_context({"chat_id": "userA"}):
        assert items.list_items() == []


def test_the_log_leaves_chat_summaries_out_unless_asked_by_kind(c):
    for kind, text in (("summary", "ملخص محادثة"), ("note", "رقم الجار")):
        assert c.post("/api/entries", json={"kind": kind, "text": text}, headers=_h()).status_code == 200
    kinds = [r["kind"] for r in c.get("/api/entries", headers=_h()).get_json()["items"]]
    assert kinds == ["note"]
    only = c.get("/api/entries?kind=summary", headers=_h()).get_json()["items"]
    assert [r["kind"] for r in only] == ["summary"]


def test_a_post_keeps_the_apps_own_id_and_a_resend_does_not_double(c):
    cid = "a" * 32
    body = {"id": cid, "list": "tasks", "text": "اشتري خبز"}
    first = c.post("/api/items", json=body, headers=_h())
    again = c.post("/api/items", json=body, headers=_h())
    assert first.get_json()["id"] == cid and again.get_json()["id"] == cid
    assert len(c.get("/api/items?list=tasks", headers=_h()).get_json()["items"]) == 1
    # Another tenant cannot take it, and a malformed one is refused.
    _bad(c.post("/api/items", json=body, headers=_h("userB")), "id_taken", 409)
    _bad(c.post("/api/entries", json={"id": "x", "kind": "note", "text": "y"}, headers=_h()),
         "invalid_id")
    r = c.post("/api/schedules", json={"id": "b" * 32, "kind": "reminder", "text": "ميتينج",
                                       "fire_at": _iso()}, headers=_h())
    assert r.get_json()["id"] == "b" * 32
    r = c.post("/api/entries", json={"id": "c" * 32, "kind": "note", "text": "فكرة"}, headers=_h())
    assert r.get_json()["id"] == "c" * 32


def test_stats_count_the_whole_log_in_the_users_days(c):
    now = datetime.now(USER_TZ)
    for kind, text, data in [("expense", "غدا", {"amount": 40}), ("expense", "قهوة", {"amount": 2.5}),
                             ("habit", "قراءة", {"habit_item_id": "h", "date": "x"}),
                             ("summary", "ملخص", None)]:
        c.post("/api/entries", json={"kind": kind, "text": text, "data": data,
                                     "at": now.isoformat()}, headers=_h())
    old = (now - timedelta(days=45)).isoformat()
    c.post("/api/entries", json={"kind": "note", "text": "قديم", "at": old}, headers=_h())
    s = c.get("/api/stats", headers=_h()).get_json()
    assert len(s["days"]) == 30 and s["days"][-1] == 3
    assert s["spent"] == 42.5 and s["habits"] == 1 and s["logged"] == 3
    assert c.get("/api/stats", headers=_h("userB")).get_json()["logged"] == 0


def test_ticking_a_repeating_task_moves_it_to_its_next_time(c):
    due = (datetime.now(USER_TZ) - timedelta(hours=2)).replace(microsecond=0)
    r = c.post("/api/items", json={"list": "tasks", "text": "اسقي الزرع", "due": due.isoformat(),
                                   "data": {"repeat": "daily"}}, headers=_h())
    iid = r.get_json()["id"]
    item = c.patch(f"/api/items/{iid}", json={"done": True}, headers=_h()).get_json()["item"]
    assert item["done"] is False
    nxt = datetime.fromisoformat(item["due"])
    assert nxt > datetime.now(USER_TZ) and nxt.hour == due.hour and nxt.minute == due.minute
    # A plain task still closes.
    plain = c.post("/api/items", json={"list": "tasks", "text": "مرة"}, headers=_h()).get_json()["id"]
    assert c.patch(f"/api/items/{plain}", json={"done": True}, headers=_h()).get_json()["item"]["done"]


def test_a_habit_keeps_its_days_and_time(c):
    r = c.post("/api/items", json={"list": "habits", "text": "جيم",
                                   "data": {"days": [1, 3, 5], "time": "18:30"}}, headers=_h())
    assert r.get_json()["item"]["data"] == {"days": [1, 3, 5], "time": "18:30"}


def test_a_budget_and_the_months_spending_by_category(c, monkeypatch):
    from app.features import users_store
    saved = {}
    monkeypatch.setattr(users_store, "set_budget", lambda uid, a: saved.update({uid: a}) or True)
    monkeypatch.setattr(users_store, "get_budget", lambda uid: saved.get(uid, 0.0))
    assert c.post("/api/budget", json={"amount": 500}, headers=_h()).get_json()["budget"] == 500
    _bad(c.post("/api/budget", json={"amount": -1}, headers=_h()), "invalid_amount")
    now = datetime.now(USER_TZ).isoformat()
    for cat, amount in [("food", 40), ("food", 10), (None, 5)]:
        data = {"amount": amount, **({"category": cat} if cat else {})}
        c.post("/api/entries", json={"kind": "expense", "text": "x", "data": data, "at": now}, headers=_h())
    s = c.get("/api/stats", headers=_h()).get_json()
    assert s["budget"] == 500 and s["by_category"] == {"food": 50, "other": 5}


def test_sandy_is_told_when_spending_nears_the_budget(monkeypatch, brain_db):  # noqa: F811
    from brain_fakes import A
    from app.brain import tools_blocks
    from app.brain.ctx import TurnCtx
    from app.features import users_store
    monkeypatch.setattr(users_store, "get_budget", lambda uid: 100.0)
    with active_user_profile_context(A):
        out = tools_blocks.remember({"kind": "expense", "text": "غدا", "data": {"amount": 50}},
                                    TurnCtx(user_id="userA"))
        assert "budget" not in out
        out = tools_blocks.remember({"kind": "expense", "text": "عشا", "data": {"amount": 40}},
                                    TurnCtx(user_id="userA"))
        assert "قرّب" in out["budget"]


def test_an_expense_with_no_category_gets_one_from_its_words(c, monkeypatch):
    from app.brain import categorize
    monkeypatch.setattr(categorize, "submit_background", lambda fn, *a, _label: fn(*a))
    monkeypatch.setattr(categorize, "classify", lambda text: "food" if "كولا" in text else "other")
    r = c.post("/api/entries", json={"kind": "expense", "text": "كولا", "data": {"amount": 20}},
               headers=_h())
    eid = r.get_json()["id"]
    from brain_fakes import A
    with active_user_profile_context(A):
        assert entries.get(eid)["data"]["category"] == "food"
    # A picked one is kept.
    r = c.post("/api/entries", json={"kind": "expense", "text": "كولا",
                                     "data": {"amount": 5, "category": "fun"}}, headers=_h())
    assert r.get_json()["item"]["data"]["category"] == "fun"
