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


# The chat's order (29 Oct 2026): the cheap Azure deployment, then the larger one on Azure
# when it fails or answers its rate limit, then OpenAI direct.
def _chain(monkeypatch, *, primary=None, fallback=None, direct=None):
    def boom(*a, **k):
        raise RuntimeError("429 exceeded token rate limit")
    asked = []

    def step(name, answer):
        def call(*a, **k):
            asked.append(name)
            if answer is None:
                return boom()
            return answer if name != "fallback" or answer != "none" else None
        return call
    monkeypatch.setattr(openai_client, "azure_is_primary", lambda: True)
    monkeypatch.setattr(model, "_primary", step("primary", primary))
    monkeypatch.setattr(model, "_azure_fallback", step("fallback", fallback))
    monkeypatch.setattr(model, "_openai_direct", step("direct", direct))
    return asked


def test_a_failed_cheap_model_goes_to_the_larger_one_on_azure(monkeypatch):
    asked = _chain(monkeypatch, fallback=_resp(_msg("من الأكبر")))
    assert model.complete([], []).text == "من الأكبر" and asked == ["primary", "fallback"]


def test_then_openai_direct_when_the_larger_one_fails_too(monkeypatch):
    asked = _chain(monkeypatch, direct=_resp(_msg("from direct")))
    assert model.complete([], []).text == "from direct"
    assert asked == ["primary", "fallback", "direct"]


def test_with_no_larger_one_set_it_goes_straight_to_openai_direct(monkeypatch):
    asked = _chain(monkeypatch, fallback="none", direct=_resp(_msg("from direct")))
    assert model.complete([], []).text == "from direct"
    assert asked == ["primary", "fallback", "direct"]


def test_a_streamed_turn_streams_from_the_larger_one(monkeypatch):
    def chunk(content):
        return NS(choices=[NS(delta=NS(content=content, tool_calls=None))])
    _chain(monkeypatch, fallback=iter([chunk("hi"), chunk(" there")]))
    seen = []
    assert model.complete([], [], on_text=seen.append).text == "hi there"
    assert seen == ["hi", "hi there"]


def test_the_larger_one_has_a_breaker_of_its_own(monkeypatch):
    # The cheap one's failures open its breaker; the fallback must not be shut by them.
    monkeypatch.setattr("app.config.AZURE_OPENAI_ENDPOINT", "https://x", raising=False)
    monkeypatch.setattr("app.config.AZURE_OPENAI_API_KEY", "k", raising=False)
    monkeypatch.setattr("app.config.AZURE_OPENAI_CHAT_FALLBACK_DEPLOYMENT", "gpt-4.1", raising=False)
    monkeypatch.setattr(openai_client, "_fallback_fn", None)
    fn = openai_client.fallback_fn()
    assert fn is not None and openai_client._cb_fallback is not openai_client._cb


# Either way round (the owner tries the cheap one first, and may set gpt-4.1 back as the
# primary): the other deployment is the fallback, and the same one is never asked twice.
def _fallback_for(monkeypatch, primary, fallback):
    monkeypatch.setattr("app.config.AZURE_OPENAI_ENDPOINT", "https://x", raising=False)
    monkeypatch.setattr("app.config.AZURE_OPENAI_API_KEY", "k", raising=False)
    monkeypatch.setattr("app.config.AZURE_OPENAI_CHAT_DEPLOYMENT", primary, raising=False)
    monkeypatch.setattr("app.config.AZURE_OPENAI_CHAT_FALLBACK_DEPLOYMENT", fallback,
                        raising=False)
    monkeypatch.setattr(openai_client, "_fallback_fn", None)
    return openai_client.fallback_fn()


def test_the_fallback_is_the_other_deployment_either_way_round(monkeypatch):
    assert _fallback_for(monkeypatch, "sandy-chat", "gpt-4.1") is not None
    assert _fallback_for(monkeypatch, "gpt-4.1", "sandy-chat") is not None


def test_a_fallback_that_is_the_primary_is_none(monkeypatch):
    assert _fallback_for(monkeypatch, "gpt-4.1", "gpt-4.1") is None
