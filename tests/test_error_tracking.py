"""Error tracking must not become a data leak.

This backend holds conversations, journals, memories and voiceprints. An error
tracker configured carelessly attaches request bodies and headers to every
report, which would ship exactly that material to a third party — and it would do
it quietly, because nobody reads their own error reports looking for other
people's diaries.

So the scrubber is tested harder than the reporting is.
"""

import os

os.environ.setdefault("JWT_SECRET", "test-secret-for-errors")

from app.integrations import error_tracking as et  # noqa: E402


# ── The scrubber ─────────────────────────────────────────────────────────────

def test_secrets_are_scrubbed_by_name():
    dirty = {
        "Authorization": "Bearer abc.def.ghi",
        "cookie": "session=xyz",
        "X-Api-Key": "sk-live-123",
        "MONGODB_URI": "mongodb+srv://user:pw@host",
        "user_agent": "Sandy/1.0",
    }
    clean = et._scrub(dirty)
    assert clean["Authorization"] == "[scrubbed]"
    assert clean["cookie"] == "[scrubbed]"
    assert clean["X-Api-Key"] == "[scrubbed]"
    assert clean["MONGODB_URI"] == "[scrubbed]"
    # Harmless keys survive, or the reports become useless.
    assert clean["user_agent"] == "Sandy/1.0"


def test_the_same_secret_is_caught_however_it_is_spelled():
    """`X-Api-Key` slipped through the first version of the scrubber.

    One idea gets four spellings depending on whether it is a header, a form
    field or a variable, and matching only one of them leaks the other three.
    """
    for spelling in ("api_key", "api-key", "apiKey", "X-Api-Key", "API KEY",
                     "access_token", "accessToken", "X-Auth-Token"):
        assert et._scrub({spelling: "secret-value"})[spelling] == "[scrubbed]", spelling


def test_scrubbing_reaches_nested_values():
    clean = et._scrub({"ctx": {"headers": {"authorization": "Bearer x"}, "path": "/api/tasks"}})
    assert clean["ctx"]["headers"]["authorization"] == "[scrubbed]"
    assert clean["ctx"]["path"] == "/api/tasks"


def test_scrubbing_survives_a_cycle():
    # Events come from a library we do not control. A hang here would turn error
    # reporting into an outage of its own.
    loop = {"a": 1}
    loop["self"] = loop
    et._scrub(loop)   # must return, not recurse forever


def test_request_body_is_never_sent():
    """A body on this backend is somebody's journal entry or what they just said."""
    event = {
        "request": {
            "data": {"text": "today I felt awful about the interview"},
            "cookies": {"session": "abc"},
            "query_string": "user_id=12345",
            "headers": {"Authorization": "Bearer secret", "Accept": "application/json"},
            "url": "/api/life/journal",
        }
    }
    out = et._before_send(event, None)
    assert "data" not in out["request"]
    assert "cookies" not in out["request"]
    assert "query_string" not in out["request"]
    assert out["request"]["headers"]["Authorization"] == "[scrubbed]"
    # The path stays — it is what locates the bug and it carries nothing personal.
    assert out["request"]["url"] == "/api/life/journal"


def test_a_failing_scrubber_drops_the_event(monkeypatch):
    """Better to lose a report than to send an unscrubbed one."""
    def explode(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(et, "_scrub", explode)
    assert et._before_send({"extra": {"x": 1}}, None) is None


# ── Startup ──────────────────────────────────────────────────────────────────

def test_no_dsn_means_no_reporting(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.setattr(et, "_started", False)
    assert et.init_error_tracking() is False


def test_capture_is_silent_when_not_started(monkeypatch):
    """Called from paths that must never raise — a heartbeat, a circuit breaker."""
    monkeypatch.setattr(et, "_started", False)
    et.capture("something odd", node_id="sandy0001")   # must not raise


def test_startup_failure_never_breaks_boot(monkeypatch):
    """Reporting is a convenience. It may not be why the backend is down."""
    monkeypatch.setenv("SENTRY_DSN", "https://bad@example.invalid/1")
    monkeypatch.setattr(et, "_started", False)
    assert et.init_error_tracking() in (True, False)   # returns either way, never raises
