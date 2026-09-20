"""Email sign-in: the rate-limit key is the router's address, and the response
names the role the token carries."""
from flask import Flask

from app.api import email_auth_api


def _ip(headers, remote="10.0.0.9"):
    app = Flask(__name__)
    with app.test_request_context("/", headers=headers,
                                  environ_base={"REMOTE_ADDR": remote}):
        return email_auth_api._client_ip()


def test_spoofed_first_hop_is_ignored():
    assert _ip({"X-Forwarded-For": "1.2.3.4, 203.0.113.7"}) == "203.0.113.7"


def test_single_hop_and_no_header():
    assert _ip({"X-Forwarded-For": "203.0.113.7"}) == "203.0.113.7"
    assert _ip({}) == "10.0.0.9"


def test_email_login_never_grants_owner(monkeypatch):
    """The address on this route is unverified: registering with the owner's
    email must not buy his tier."""
    from app import config
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setattr(config, "SANDY_OWNER_EMAILS", "o@x.y", raising=False)
    app = Flask(__name__)
    with app.test_request_context("/"):
        resp, status = email_auth_api._result_for({"_id": "u1", "email": "o@x.y"})
    assert status == 200 and resp.get_json()["role"] == "user"


def _app(monkeypatch):
    import mongomock

    from app.api.server import create_app
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    db = mongomock.MongoClient().db
    return create_app(mongo_db=db, semantic_memory_stats_fn=lambda: {}), db


def _bearer(role="user", uid="u1"):
    from app.api.auth_handlers import make_token
    return {"Authorization": f"Bearer {make_token(role, user_id=uid)}"}


def test_image_endpoints_meter_signed_in_users(monkeypatch):
    app, _ = _app(monkeypatch)
    from app.features import usage_store
    monkeypatch.setattr(usage_store, "check_and_record",
                        lambda *a, **k: "daily_quota_exceeded")
    c = app.test_client()
    for path, body in (("/api/image", {"prompt": "x"}),
                       ("/api/image/edit", {"prompt": "x", "image": "aGk="}),
                       ("/api/analyze-image", {"image": "aGk="})):
        r = c.post(path, json=body, headers=_bearer())
        assert r.status_code == 429, path


def test_bad_base64_is_a_400(monkeypatch):
    app, _ = _app(monkeypatch)
    from app.features import usage_store
    monkeypatch.setattr(usage_store, "check_and_record", lambda *a, **k: None)
    c = app.test_client()
    r = c.post("/api/analyze-image", json={"image": "not base64!!"}, headers=_bearer())
    assert r.status_code == 400


def test_chat_history_is_capped_and_typed(monkeypatch):
    app, db = _app(monkeypatch)
    c = app.test_client()
    assert c.put("/api/chat/history", json={"messages": "x"},
                 headers=_bearer()).status_code == 400
    c.put("/api/chat/history", json={"messages": list(range(900))}, headers=_bearer())
    doc = db.web_chat_history.find_one({"_id": "web_chat_u1"})
    assert len(doc["messages"]) == 500 and doc["messages"][-1] == 899


def test_social_owner_tier_needs_a_vouched_email(monkeypatch):
    from app.api import social_auth_api as sa
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setattr(sa, "role_for_email", lambda e: "owner")
    monkeypatch.setattr(sa.users_store, "upsert_from_oauth",
                        lambda *a, **k: {"_id": "u1", "email": "o@x.y"})
    app = Flask(__name__)
    with app.test_request_context("/"):
        resp, _ = sa._issue_for_identity(provider="google", sub="s", email="o@x.y",
                                         name="", picture="", email_trusted=False)
        assert resp.get_json()["role"] == "user"
        resp, _ = sa._issue_for_identity(provider="google", sub="s", email="o@x.y",
                                         name="", picture="", email_trusted=True)
        assert resp.get_json()["role"] == "owner"
    assert sa._is_true("true") and sa._is_true(True) and not sa._is_true("false")


def test_paid_routes_are_metered(monkeypatch):
    """Every route that calls a paid provider charges the caller's quota."""
    app, _ = _app(monkeypatch)
    from app.features import usage_store
    monkeypatch.setattr(usage_store, "check_and_record",
                        lambda *a, **k: "daily_quota_exceeded")
    c = app.test_client()
    h = _bearer()
    assert c.get("/api/research?q=x", headers=h).status_code == 429
    assert c.post("/api/gifts/generate", json={}, headers=h).status_code == 429
    assert c.post("/api/plans/active/finish", headers=h).status_code == 429


def test_non_numeric_body_fields_are_a_400(monkeypatch):
    app, _ = _app(monkeypatch)
    c = app.test_client()
    h = _bearer()
    r = c.post("/api/life/books", json={"title": "x", "total_pages": "abc"}, headers=h)
    assert r.status_code == 400 and r.get_json()["error"] == "invalid_request"
    assert c.post("/api/life/focus/start", json={"focus_min": "x"}, headers=h).status_code == 400
    assert c.get("/api/life/expenses?days=abc", headers=h).status_code == 400
