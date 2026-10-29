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
    background.call("title", [{"role": "user", "content": "x"}], priority=background.BACKGROUND)
    monkeypatch.setenv("SANDY_BACKGROUND_MODELS", '{"task": "gpt-4.1"}')
    background.call("task", [{"role": "user", "content": "x"}], priority=background.SCHEDULED)
    background.call("title", [{"role": "user", "content": "x"}], priority=background.BACKGROUND)
    assert [k["model_hint"] for k in asked] == [None, "gpt-4.1", None]


def test_settings_that_are_not_json_are_the_chats_model(monkeypatch, asked):
    monkeypatch.setenv("SANDY_BACKGROUND_MODELS", "gpt-4.1")
    background.call("task", [], priority=background.SCHEDULED)
    assert asked[0]["model_hint"] is None


def test_outside_a_turn_it_is_a_background_row_inside_one_it_is_the_turns(monkeypatch, asked):
    rows = []
    monkeypatch.setattr(trace_store, "background",
                        lambda uid, what: rows.append((uid, what)) or trace_store.using(None))
    background.call("title", [], priority=background.BACKGROUND, user_id="u1")
    with trace_store.using(trace_store.Trace("u1", "chat")):
        background.call("when", [], priority=background.DIRECT, user_id="u1")
    assert rows == [("u1", "title")]


# Every call says how urgent it is (owner, 29 Oct 2026): what the user waits on runs at once,
# never behind background work and never as a batch; only a scheduled task may be batched.
def test_every_call_names_its_priority(asked):
    with pytest.raises(TypeError):
        background.call("title", [])                     # no priority: refused
    with pytest.raises(ValueError):
        background.call("title", [], priority="soon")    # not one of the three


@pytest.mark.parametrize("priority, batchable", [(background.DIRECT, False),
                                                 (background.BACKGROUND, False),
                                                 (background.SCHEDULED, True)])
def test_only_a_scheduled_call_may_be_batched(priority, batchable):
    assert background.may_batch(priority) is batchable


def test_a_direct_call_does_not_wait_when_the_background_pool_is_full(asked):
    import threading
    import time

    from app.utils.thread_pool import sandy_executor, submit_background
    release = threading.Event()
    for _ in range(sandy_executor._max_workers * 2):
        submit_background(release.wait, 5)
    try:
        t0 = time.perf_counter()
        background.call("when", [], priority=background.DIRECT)
        assert time.perf_counter() - t0 < 0.5 and asked
    finally:
        release.set()


def test_the_callers_say_their_priority(monkeypatch):
    """What the user waits on is direct; the rest is background; a task is scheduled."""
    import ast
    from pathlib import Path
    want = {"when": "DIRECT", "web_summary": "DIRECT", "vision": "DIRECT",
            "stm_summary": "BACKGROUND", "title": "BACKGROUND", "photo_tags": "BACKGROUND",
            "categorize": "BACKGROUND", "daily_nudge": "BACKGROUND",
            "task": "SCHEDULED", "task_review": "SCHEDULED", "task_check": "DIRECT"}
    root = Path(__file__).resolve().parents[1] / "cloud" / "app"
    found = {}
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "call" \
                    and getattr(node.func.value, "id", "") == "background" and node.args \
                    and isinstance(node.args[0], ast.Constant):
                kw = {k.arg: k.value for k in node.keywords}
                found[node.args[0].value] = getattr(kw.get("priority"), "attr", None)
    assert found == want
