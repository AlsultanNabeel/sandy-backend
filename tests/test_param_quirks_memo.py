"""A deployment's rejected parameters are learned once, not on every call."""
from unittest.mock import MagicMock

import pytest

from app.integrations import azure_intent_client as aic


class _Rejected(Exception):
    def __init__(self, param):
        super().__init__(f"Unsupported parameter: '{param}'")
        self.param = param


@pytest.fixture(autouse=True)
def _clean():
    aic._ADAPTED.clear()
    yield
    aic._ADAPTED.clear()


def _client(reject):
    calls = []

    def create(**kw):
        calls.append(dict(kw))
        for p in reject:
            if p in kw:
                raise _Rejected(p)
        return "ok"

    client = MagicMock()
    client.chat.completions.create.side_effect = create
    return client, calls


def test_rejected_param_costs_one_round_trip_once():
    client, calls = _client({"reasoning_effort"})
    kw = {"model": "m1", "messages": [], "reasoning_effort": "minimal"}
    assert aic._create_chat_adapting(client, kw) == "ok"
    assert len(calls) == 2
    calls.clear()
    assert aic._create_chat_adapting(client, kw) == "ok"
    assert len(calls) == 1 and "reasoning_effort" not in calls[0]


def test_rename_is_remembered():
    client, calls = _client({"max_tokens"})
    kw = {"model": "m2", "messages": [], "max_tokens": 50}
    aic._create_chat_adapting(client, kw)
    calls.clear()
    aic._create_chat_adapting(client, kw)
    assert calls == [{"model": "m2", "messages": [], "max_completion_tokens": 50}]


def test_quirks_are_per_model():
    client, calls = _client({"reasoning_effort"})
    aic._create_chat_adapting(client, {"model": "a", "messages": [], "reasoning_effort": "x"})
    calls.clear()
    ok_client, ok_calls = _client(set())
    aic._create_chat_adapting(ok_client, {"model": "b", "messages": [], "reasoning_effort": "x"})
    assert ok_calls[0].get("reasoning_effort") == "x"


def test_caller_kwargs_not_mutated():
    client, _ = _client({"reasoning_effort"})
    kw = {"model": "m3", "messages": [], "reasoning_effort": "minimal"}
    aic._create_chat_adapting(client, kw)
    aic._create_chat_adapting(client, kw)
    assert kw["reasoning_effort"] == "minimal"


def test_chat_path_uses_the_adapter(monkeypatch):
    from app.integrations import openai_client
    from app.utils.circuit_breaker import CircuitBreaker
    # A fresh breaker: the module one is shared, and an earlier test may have
    # left it open.
    monkeypatch.setattr(openai_client, "_cb", CircuitBreaker(name="t", failure_threshold=5))
    client, calls = _client({"temperature"})
    openai_client.create_chat_completion([], client, openai_model="m4", prefer_azure=False)
    assert "temperature" not in calls[-1]
