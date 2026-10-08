"""The model adapter: native tool calls (plain and streamed) and the fallback chain."""
from __future__ import annotations

from types import SimpleNamespace as NS

from app.brain import model
from app.integrations import openai_client


def _msg(content=None, calls=()):
    return NS(content=content, tool_calls=[
        NS(id=f"id{i}", function=NS(name=n, arguments=a)) for i, (n, a) in enumerate(calls)])


def _resp(msg):
    return NS(choices=[NS(message=msg)])


def test_a_plain_message_with_tool_calls(monkeypatch):
    monkeypatch.setattr(model, "_primary", lambda m, t, stream: _resp(
        _msg(calls=[("recall", '{"query": "جيم"}'), ("weather", "not json")])))
    r = model.complete([], [])
    assert [(c.name, c.args) for c in r.tool_calls] == [("recall", {"query": "جيم"}),
                                                       ("weather", {})]


def test_a_streamed_answer_arrives_cumulatively_and_tool_calls_reassemble(monkeypatch):
    def chunk(content=None, tc=None):
        return NS(choices=[NS(delta=NS(content=content, tool_calls=tc))])

    chunks = [
        chunk("أه"), chunk("لين"),
        chunk(tc=[NS(index=0, id="c1", function=NS(name="list_", arguments='{"te'))]),
        chunk(tc=[NS(index=0, id=None, function=NS(name="add", arguments='xt": "خبز"}'))]),
    ]
    monkeypatch.setattr(model, "_primary", lambda m, t, stream: iter(chunks))
    seen = []
    r = model.complete([], [], on_text=seen.append)
    assert seen == ["أه", "أهلين"] and r.text == "أهلين"
    assert [(c.id, c.name, c.args) for c in r.tool_calls] == [("c1", "list_add", {"text": "خبز"})]


def test_primary_down_falls_to_openai_direct(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("azure down")

    # Azure as the primary is what the fallback hangs on; set here, not by a local .env.
    monkeypatch.setattr(openai_client, "azure_is_primary", lambda: True)
    monkeypatch.setattr(model, "_primary", boom)
    monkeypatch.setattr(model, "_openai_direct", lambda m, t: _resp(_msg("من الاحتياطي")))
    assert model.complete([], []).text == "من الاحتياطي"
    monkeypatch.setattr(model, "_openai_direct", lambda m, t: None)
    assert model.complete([], []) is None


def test_with_openai_direct_as_the_primary_there_is_no_second_try(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("openai down")

    monkeypatch.setattr(openai_client, "azure_is_primary", lambda: False)
    monkeypatch.setattr(model, "_primary", boom)
    monkeypatch.setattr(model, "_openai_direct", lambda m, t: _resp(_msg("مرة تانية")))
    assert model.complete([], []) is None
