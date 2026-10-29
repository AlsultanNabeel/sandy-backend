"""Every model call outside a reply's own loop goes through one function (`brain/background.py`):
the model for each kind of work from the settings, the chat's own by default, and its trace."""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from app.brain import background
from app.features import trace_store


@pytest.fixture
def asked(monkeypatch):
    seen = []

    def fn(**kw):
        seen.append(kw)
        return NS(choices=[NS(message=NS(content="ok"))])
    monkeypatch.setattr("app.integrations.openai_client.chat_fn", lambda: fn)
    return seen


def test_the_chats_own_model_unless_the_settings_name_one(monkeypatch, asked):
    monkeypatch.delenv("SANDY_BACKGROUND_MODELS", raising=False)
    background.call("title", [{"role": "user", "content": "x"}])
    monkeypatch.setenv("SANDY_BACKGROUND_MODELS", '{"task": "gpt-4.1"}')
    background.call("task", [{"role": "user", "content": "x"}])
    background.call("title", [{"role": "user", "content": "x"}])
    assert [k["model_hint"] for k in asked] == [None, "gpt-4.1", None]


def test_settings_that_are_not_json_are_the_chats_model(monkeypatch, asked):
    monkeypatch.setenv("SANDY_BACKGROUND_MODELS", "gpt-4.1")
    background.call("task", [])
    assert asked[0]["model_hint"] is None


def test_outside_a_turn_it_is_a_background_row_inside_one_it_is_the_turns(monkeypatch, asked):
    rows = []
    monkeypatch.setattr(trace_store, "background",
                        lambda uid, what: rows.append((uid, what)) or trace_store.using(None))
    background.call("title", [], user_id="u1")
    with trace_store.using(trace_store.Trace("u1", "chat")):
        background.call("when", [], user_id="u1")
    assert rows == [("u1", "title")]
