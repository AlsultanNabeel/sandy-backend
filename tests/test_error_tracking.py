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


def test_breadcrumbs_keep_the_tag_not_the_words():
    """INFO lines name task text and search queries; they ride along as crumbs."""
    event = {
        "breadcrumbs": {"values": [
            {"message": "[TasksStore] added: اشتري هدية لسارة", "data": {"q": "x"}},
            {"message": "plain line with a secret"},
        ]},
        "logentry": {"message": "[x] failed for %s", "params": ["sara@example.com"],
                     "formatted": "[x] failed for sara@example.com"},
    }
    out = et._before_send(event, None)
    crumbs = out["breadcrumbs"]["values"]
    assert crumbs[0]["message"] == "[TasksStore]" and "data" not in crumbs[0]
    assert crumbs[1]["message"] == "[redacted]"
    assert "params" not in out["logentry"] and "formatted" not in out["logentry"]
    assert out["logentry"]["message"] == "[x] failed for %s"


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


def test_startup_failure_never_breaks_boot(monkeypatch):
    """Reporting is a convenience. It may not be why the backend is down."""
    monkeypatch.setenv("SENTRY_DSN", "https://bad@example.invalid/1")
    monkeypatch.setattr(et, "_started", False)
    assert et.init_error_tracking() in (True, False)   # returns either way, never raises


# ── What a crash carries ─────────────────────────────────────────────────────

def test_frame_variables_never_leave():
    """A stack frame's variables are the message, the photo, the transcript being
    worked on when it broke."""
    event = {"exception": {"values": [{"stacktrace": {"frames": [
        {"function": "run_turn", "vars": {"message": "مصروفي على الدكتور النفسي"}},
        {"function": "save"},
    ]}}]}, "threads": {"values": [{"stacktrace": {"frames": [
        {"function": "worker", "vars": {"text": "سرّي"}}]}}]}}
    out = et._before_send(event, None)
    frames = out["exception"]["values"][0]["stacktrace"]["frames"]
    assert all("vars" not in f for f in frames)
    assert "vars" not in out["threads"]["values"][0]["stacktrace"]["frames"][0]


def test_reporting_starts_without_locals_and_scrubs_traces(monkeypatch):
    """Locals are off at the source, and a performance trace (which never passes
    `before_send`) goes through the same scrubber, so its query string is dropped."""
    import sys
    import types

    seen = {}
    fake = types.ModuleType("sentry_sdk")
    fake.init = lambda **kw: seen.update(kw)
    integrations = types.ModuleType("sentry_sdk.integrations")
    flask = types.ModuleType("sentry_sdk.integrations.flask")
    flask.FlaskIntegration = lambda: None
    logging_mod = types.ModuleType("sentry_sdk.integrations.logging")
    logging_mod.LoggingIntegration = lambda **_k: None
    for name, mod in (("sentry_sdk", fake), ("sentry_sdk.integrations", integrations),
                      ("sentry_sdk.integrations.flask", flask),
                      ("sentry_sdk.integrations.logging", logging_mod)):
        monkeypatch.setitem(sys.modules, name, mod)
    from app import config
    monkeypatch.setattr(config, "SENTRY_DSN", "https://k@example.invalid/1")
    monkeypatch.setattr(et, "_started", False)

    assert et.init_error_tracking() is True
    assert seen["include_local_variables"] is False
    trace = seen["before_send_transaction"](
        {"type": "transaction", "request": {"url": "https://x/api/entries",
                                             "query_string": "q=مصروفي"}}, None)
    assert "query_string" not in trace["request"]
