"""Each model call outside a reply's loop goes through `background.call`, named by its kind of
work, so its model is set per kind and one place can limit them all."""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest
from brain_fakes import A, brain_db  # noqa: F401

from app.brain import background
from app.utils.user_profiles import active_user_profile_context


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def call(what, messages, **kw):
        seen.append({"what": what, **kw})
        return NS(choices=[NS(message=NS(content=kw.pop("answer", "ok")))])
    monkeypatch.setattr(background, "call", call)
    return seen


def test_the_stm_summary(brain_db, calls):  # noqa: F811
    from app.brain import stm
    with active_user_profile_context(A):
        stm._summarize("t1", "userA", [{"role": "user", "content": "hi"}], "chat")
    assert calls == [{"what": "stm_summary", "priority": "background", "user_id": "userA",
                      "max_tokens": 200}]


def test_a_chats_title(calls):
    import mongomock

    from app.api import conversations_api
    conversations_api._generate_title(mongomock.MongoClient().db.c, "c1", "userA", "hi", "hello")
    assert [(c["what"], c["user_id"], c["max_tokens"]) for c in calls] == [("title", "userA", 20)]


def test_the_daily_nudge(calls, monkeypatch):
    from app.api import daily_nudge_api as nudge
    monkeypatch.setattr(nudge, "build_effective_persona", lambda uid: "p")
    out = nudge._generate_agenda("userA", {"tasks": 1, "overdue": 0, "reminders": 0, "titles": []})
    assert out == "ok" and [(c["what"], c["user_id"]) for c in calls] == [("daily_nudge", "userA")]


def test_a_photos_tags(monkeypatch):
    from app.features import photo_album
    seen = []
    monkeypatch.setattr(background, "call", lambda what, messages, **kw: seen.append((what, kw)) or NS(
        choices=[NS(message=NS(content='{"caption": "c", "tags": ["a", "b"]}'))]))
    assert photo_album.generate_tags(b"img", "userA") == ("c", ["a", "b"])
    assert seen[0][0] == "photo_tags" and seen[0][1]["user_id"] == "userA"


def test_an_expenses_category(calls):
    from app.brain import categorize
    with active_user_profile_context(A):
        assert categorize.classify("قهوة") == "other"
    assert [(c["what"], c["user_id"], c["max_tokens"]) for c in calls] == [("categorize", "userA", 4)]


def test_a_time_read_from_words(monkeypatch):
    from app.brain import when
    seen = []
    monkeypatch.setattr(background, "call", lambda what, messages, **kw: seen.append((what, kw)) or NS(
        choices=[NS(message=NS(content='{"success": false}'))]))
    assert when._parse_with_model("بعد العيد") is None
    assert seen[0][0] == "when" and seen[0][1]["response_format"] == {"type": "json_object"}


def test_a_web_summary(monkeypatch):
    from app.features import research
    monkeypatch.setattr(research, "EXA_API_KEY", "k")
    monkeypatch.setattr(research, "search_exa", lambda *a, **k: [
        {"title": "T", "text": "body", "url": "https://example.com/a"}])
    seen = []
    monkeypatch.setattr(background, "call", lambda what, messages, **kw: seen.append((what, kw)) or NS(
        choices=[NS(message=NS(content="the summary"))]))
    with active_user_profile_context(A):
        assert "the summary" in research.web_answer("q", "what is new?")
    assert seen[0][0] == "web_summary" and seen[0][1]["user_id"] == "userA"


def test_an_images_answer(calls, monkeypatch):
    from app.features import vision
    monkeypatch.setattr(vision, "_build_sandy_vision_system", lambda uid: "s")
    assert vision.analyze_image_with_azure(b"img", "what is it?", user_id="userA") == "ok"
    assert [(c["what"], c["user_id"]) for c in calls] == [("vision", "userA")]


def test_no_model_call_is_made_outside_the_one_function():
    """Every model call outside a reply's loop is `background.call`: the chat's own client is
    called directly in the model adapter alone (`brain/model.py`)."""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "cloud" / "app"
    allowed = {"brain/background.py", "brain/model.py", "integrations/openai_client.py"}
    found = [str(p.relative_to(root)) for p in root.rglob("*.py")
             if str(p.relative_to(root)) not in allowed
             and re.search(r"chat_fn\(\)\s*\(|import chat_fn|chat\.completions\.create",
                           p.read_text(encoding="utf-8"))]
    assert not found, found


def test_a_batch_goes_through_the_one_function_too():
    """A batch job is submitted and collected through `background` alone (review of phase one):
    `brain/batch.py` is Azure's client for it, called from nowhere else."""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "cloud" / "app"
    allowed = {"brain/background.py", "brain/batch.py"}
    found = [str(p.relative_to(root)) for p in root.rglob("*.py")
             if str(p.relative_to(root)) not in allowed
             and re.search(r"batch\.(submit|collect|enabled)\(|from app\.brain import .*\bbatch\b",
                           p.read_text(encoding="utf-8"))]
    assert not found, found


def test_a_batch_is_submitted_by_call_and_collected_into_the_trace(monkeypatch):
    from app.brain import batch
    from app.features import trace_store
    monkeypatch.setenv("SANDY_BATCH_DEPLOYMENT", "sandy-batch")
    sent = []
    monkeypatch.setattr(batch, "submit", lambda what, messages, **kw: sent.append((what, kw)) or "b1")
    monkeypatch.setattr(batch, "collect", lambda job: (
        trace_store.note_model_call("azure_batch", "gpt-4o-mini", tokens_in=10, tokens_out=2) or "hi"))
    assert background.call("task", [], priority=background.SCHEDULED, as_batch=True,
                           max_tokens=7, temperature=0.3) == "b1"
    assert sent == [("task", {"max_tokens": 7, "temperature": 0.3})]
    with pytest.raises(ValueError):
        background.call("title", [], priority=background.BACKGROUND, as_batch=True)
    trace = trace_store.Trace("userA", "background")
    with trace_store.using(trace):
        assert background.collect("task", "b1") == "hi"
    assert [c["what"] for c in trace.model_calls] == ["task"]
