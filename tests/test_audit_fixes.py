"""Behaviour asserted for each fix from the September audit.

One test per defect, named after what a user would have seen. Source-inspection
tests live with their own subjects (`test_memory_is_one_memory`,
`test_speaker_id`, `test_review_tenant_guard`); this file is the behavioural half.
"""
from __future__ import annotations

import base64

import mongomock
import pytest


def _app(monkeypatch):
    from app.api.server import create_app
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    db = mongomock.MongoClient().db
    return create_app(mongo_db=db), db


def _bearer(role="user", uid="u1"):
    from app.api.auth_handlers import make_token
    return {"Authorization": f"Bearer {make_token(role, user_id=uid)}"}


# ── AUD-AUTH-001 — an ID token has to have been minted for *this* app ────────

def test_social_sign_in_refuses_in_prod_when_the_audience_is_not_configured(monkeypatch):
    """Without the expected audience, a token minted for any other Google app is
    accepted here as that person signing in. It used to skip the check and log a
    warning; now it refuses."""
    from app.api import social_auth_api

    monkeypatch.setattr(social_auth_api, "APP_ENV", "prod")
    with pytest.raises(social_auth_api._AudienceNotConfigured):
        social_auth_api._expected_audience("", "google")

    # Configured: the check runs.
    assert social_auth_api._expected_audience("client-123", "google") == "client-123"


def test_a_laptop_can_still_sign_in_without_an_oauth_client(monkeypatch):
    """Outside prod the skip stays, or a backend on a laptop cannot sign in
    before the OAuth client exists. It says so at warning level."""
    from app.api import social_auth_api

    monkeypatch.setattr(social_auth_api, "APP_ENV", "dev")
    assert social_auth_api._expected_audience("", "apple") is None


# ── AUD-PHOTO-001 / AUD-CLOUD-003 — a bound before the expensive part ────────

def test_an_oversized_photo_is_refused_before_it_is_decoded(monkeypatch):
    from app.api import photos_api

    app, _ = _app(monkeypatch)
    huge = "A" * (photos_api._MAX_PHOTO_B64_CHARS + 4)
    r = app.test_client().post("/api/photos", json={"image": huge}, headers=_bearer())
    assert r.status_code == 413
    assert r.get_json()["error"] == "image_too_large"


def test_a_reasonable_photo_is_not_caught_by_the_bound(monkeypatch):
    """The guard must not be the thing that breaks ordinary uploads."""
    from app.api import photos_api

    app, _ = _app(monkeypatch)
    ok = base64.b64encode(b"\xff\xd8\xff" + b"x" * 2000).decode()
    assert len(ok) < photos_api._MAX_PHOTO_B64_CHARS
    r = app.test_client().post("/api/photos", json={"image": ok}, headers=_bearer())
    assert r.status_code != 413


def test_an_enormous_image_prompt_never_reaches_the_provider(monkeypatch):
    from app.api import server as server_mod

    app, _ = _app(monkeypatch)
    long_prompt = "ا" * (server_mod._MAX_IMAGE_PROMPT_CHARS + 1)

    def _must_not_run(*_a, **_k):
        raise AssertionError("the image provider was called with an unbounded prompt")

    monkeypatch.setattr("app.features.vision.generate_image_with_azure", _must_not_run)
    c = app.test_client()
    for path, body in (("/api/image", {"prompt": long_prompt}),
                       ("/api/image/edit", {"prompt": long_prompt, "image": "aGk="})):
        r = c.post(path, json=body, headers=_bearer())
        assert r.status_code == 413, path


# ── AUD-DB-001 — "up but knows nothing" is the outage nobody notices ─────────

def test_a_dead_database_stops_production_instead_of_serving_amnesia(monkeypatch):
    """The log used to say it was falling back to JSON memory. That store was
    removed: the real behaviour was Sandy answering every read with nothing and
    discarding every write, while looking healthy."""
    from app.integrations import mongodb_store

    monkeypatch.setattr(mongodb_store, "APP_ENV", "prod")
    monkeypatch.setattr(mongodb_store, "_connect_mongo",
                        lambda _uri: (_ for _ in ()).throw(OSError("no route to host")))
    with pytest.raises(RuntimeError):
        mongodb_store.init_mongo_connection("mongodb://x/y", "db")

    monkeypatch.setattr(mongodb_store, "APP_ENV", "prod")
    with pytest.raises(RuntimeError):
        mongodb_store.init_mongo_connection("", "db")


def test_a_laptop_still_boots_without_a_database(monkeypatch):
    """The package imports and the tests run with no credentials, deliberately."""
    from app.integrations import mongodb_store

    monkeypatch.setattr(mongodb_store, "APP_ENV", "dev")
    assert mongodb_store.init_mongo_connection("", "db") == (None, None)


# ── AUD-CLOUD-002 — the tenant guard is an allowlist now ────────────────────

def test_a_pipeline_stage_that_cannot_be_guarded_is_refused():
    """`$replaceWith` can hand a document to another tenant exactly as surely as
    `$set` can, and unlike `$set` there is no field to rewrite — only an
    expression whose result the server computes. Passing it through untouched
    was the wrong default for this file."""
    from app.utils.tenant_db import ScopedCollection

    raw = mongomock.MongoClient().db.things
    coll = ScopedCollection(raw, "a", bump=False)

    for stage in ({"$replaceWith": {"user_id": "b"}},
                  {"$replaceRoot": {"newRoot": "$other"}},
                  {"$project": {"user_id": 0}}):
        with pytest.raises(ValueError):
            coll._guard_update([stage])


def test_the_dictionary_spelling_of_unset_cannot_smuggle_the_tenant_field_out():
    from app.utils.tenant_db import ScopedCollection

    raw = mongomock.MongoClient().db.things
    coll = ScopedCollection(raw, "a", bump=False)
    assert coll._guard_update([{"$unset": {"user_id": "", "n": ""}}]) == \
        [{"$unset": {"n": ""}}]
    with pytest.raises(ValueError):
        coll._guard_update([{"$unset": {"user_id": ""}}])
    with pytest.raises(ValueError):
        coll._guard_update([{"$unset": ["user_id"]}])


# ── AUD-AGENT-001 — a failed index must not end the attempts ────────────────

def test_a_failed_stm_index_is_retried_rather_than_given_up_on(monkeypatch):
    """The flag was set whatever happened, so one Mongo blip during the first
    chat turn after a deploy cost this process the `(user_id, updated_at)` index
    for its whole life — and losing that one makes every reply get slower as
    everybody else's history grows, which nobody reports as a bug."""
    from app.brain import stm

    attempts = {"n": 0}

    class _Coll:
        def create_index(self, *_a, **_k):
            attempts["n"] += 1
            if attempts["n"] <= 3:       # the whole first pass fails
                raise RuntimeError("transient")

    monkeypatch.setattr(stm, "_stm_index_ready", False)
    monkeypatch.setattr("app.db.get_db", lambda: {"sandy_stm": _Coll()})

    stm._stm_collection()
    assert stm._stm_index_ready is False, "a failed pass must not latch"
    stm._stm_collection()
    assert stm._stm_index_ready is True, "a successful pass must stop the retries"

    before = attempts["n"]
    stm._stm_collection()
    assert attempts["n"] == before, "it must not keep retrying after success"


# ── AUD-BOOT-001 — one worker per machine runs the periodic jobs ────────────

def test_only_one_process_on_this_machine_claims_a_job():
    from app.utils.process_leader import _held, claim_leadership

    _held.pop("pytest-job", None)
    assert claim_leadership("pytest-job") is True
    # The same process asking twice is the same holder, not a second one.
    assert claim_leadership("pytest-job") is True
    assert "pytest-job" in _held
