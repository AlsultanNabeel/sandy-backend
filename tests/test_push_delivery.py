"""Push delivery — device-token store, APNs gating, and the daily scheduler.

No Apple account and no network: APNs is exercised only through ``is_configured``
and the send-when-unconfigured guard, and the scheduler's fan-out runs against a
mongomock DB with ``apns.send`` monkeypatched. The headline guarantees:

  * a device token binds to exactly one user and re-registration re-owns it;
  * with no Apple keys the whole delivery path is inert (no thread, no send);
  * the scheduler pushes each user's nudge once and prunes dead tokens;
  * a second same-day run is a no-op (the per-day lock dedups gunicorn workers).
"""

import os

import mongomock
import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-for-push")

from app.features import push_tokens_store  # noqa: E402
from app.services import apns, nudge_scheduler  # noqa: E402
from app.utils.user_profiles import active_user_profile_context  # noqa: E402


@pytest.fixture()
def db():
    database = mongomock.MongoClient().db
    push_tokens_store.init_push_tokens_store(database)
    return database


# ── token store ──────────────────────────────────────────────────────────

def test_register_binds_token_to_user(db):
    assert push_tokens_store.register_token("u1", "tokenA") is True
    assert push_tokens_store.tokens_for_user("u1") == ["tokenA"]
    assert push_tokens_store.user_ids_with_tokens() == ["u1"]


def test_reregister_reowns_device(db):
    push_tokens_store.register_token("u1", "tokenA")
    push_tokens_store.register_token("u2", "tokenA")  # phone handed to u2
    assert push_tokens_store.tokens_for_user("u1") == []
    assert push_tokens_store.tokens_for_user("u2") == ["tokenA"]


def test_unregister_and_blank_inputs(db):
    push_tokens_store.register_token("u1", "tokenA")
    assert push_tokens_store.unregister_token("tokenA") is True
    assert push_tokens_store.tokens_for_user("u1") == []
    assert push_tokens_store.register_token("u1", "") is False
    assert push_tokens_store.register_token("", "tokenB") is False


# ── APNs gating ────────────────────────────────────────────────────────────

def test_unconfigured_is_inert(monkeypatch):
    for var in ("APNS_KEY_P8", "APNS_KEY_ID", "APNS_TEAM_ID", "APNS_BUNDLE_ID"):
        monkeypatch.delenv(var, raising=False)
    assert apns.is_configured() is False
    ok, status = apns.send("tok", "t", "b")
    assert ok is False and status == "not_configured"


def test_configured_signs_provider_token(monkeypatch):
    # A throwaway EC P-256 key in .p8 form — enough to prove is_configured()
    # flips and the ES256 provider JWT actually signs.
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    p8 = ec.generate_private_key(ec.SECP256R1()).private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    monkeypatch.setenv("APNS_KEY_P8", p8)
    monkeypatch.setenv("APNS_KEY_ID", "ABCDE12345")
    monkeypatch.setenv("APNS_TEAM_ID", "TEAM123456")
    monkeypatch.setenv("APNS_BUNDLE_ID", "com.sandy.app")
    apns._cached_token, apns._cached_at = None, 0.0
    assert apns.is_configured() is True
    assert apns._provider_token()  # signs without raising


# ── scheduler fan-out ───────────────────────────────────────────────────────

def test_scheduler_idle_without_keys(db, monkeypatch):
    for var in ("APNS_KEY_P8", "APNS_KEY_ID", "APNS_TEAM_ID", "APNS_BUNDLE_ID"):
        monkeypatch.delenv(var, raising=False)
    nudge_scheduler._started = False
    assert nudge_scheduler.start_nudge_scheduler(db) is False
    assert nudge_scheduler._scheduler is None


def test_daily_send_delivers_and_prunes_dead_tokens(db, monkeypatch):
    push_tokens_store.register_token("u1", "live")
    push_tokens_store.register_token("u1", "dead")

    import app.api.daily_nudge_api as nudge_api
    monkeypatch.setattr(
        nudge_api, "get_daily_nudge",
        lambda mongo_db, uid: {"kind": "agenda", "text": "صباح الخير"},
    )

    sent = []

    def fake_send(token, title, body, data=None):
        sent.append(token)
        return (False, "gone") if token == "dead" else (True, "ok")

    monkeypatch.setattr(apns, "send", fake_send)

    delivered = nudge_scheduler.run_daily_send(db)
    assert delivered == 1
    assert set(sent) == {"live", "dead"}
    assert push_tokens_store.tokens_for_user("u1") == ["live"]  # dead pruned


def test_daily_send_is_deduped_per_day(db, monkeypatch):
    push_tokens_store.register_token("u1", "live")
    import app.api.daily_nudge_api as nudge_api
    monkeypatch.setattr(
        nudge_api, "get_daily_nudge",
        lambda mongo_db, uid: {"kind": "agenda", "text": "x"},
    )
    monkeypatch.setattr(apns, "send", lambda *a, **k: (True, "ok"))

    assert nudge_scheduler.run_daily_send(db) == 1
    assert nudge_scheduler.run_daily_send(db) == 0  # lock held → skipped


# ── refactored nudge builder (question vs cached agenda) ─────────────────────

def test_get_daily_nudge_question_then_cached(monkeypatch):
    from app.features import users_store
    import app.api.daily_nudge_api as nudge_api

    database = mongomock.MongoClient().db
    users_store.init_users_store(database)
    users_store.create_email_user("q@x.com", "hash")
    uid = users_store.get_email_user("q@x.com")["_id"]

    monkeypatch.setattr(nudge_api, "_is_question_day", lambda: True)
    with active_user_profile_context(
        {"chat_id": uid, "permissions": "all", "relation": "user"}
    ):
        first = nudge_api.get_daily_nudge(database, uid)
        assert first["kind"] == "question" and first["qid"] == "unwind"
        # Cached: even if it were now an agenda day, we get the same doc back.
        monkeypatch.setattr(nudge_api, "_is_question_day", lambda: False)
        again = nudge_api.get_daily_nudge(database, uid)
        assert again == first
