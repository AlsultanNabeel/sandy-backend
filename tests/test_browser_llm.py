"""The model browser-use drives a fill with (`brain/browser_llm.py`) is ours: every step goes
through `background.call("browser_step")`, the one door every model call outside a reply goes
through, so it is traced, priced and capped like the rest, under his account; a structured step
comes back as browser-use's own model; a failure is browser-use's provider error, never a crash."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace as NS

import pytest
from pydantic import BaseModel

from app.brain import background, browser_llm


class Step(BaseModel):
    thinking: str
    action: str


def _answer(text):
    return NS(choices=[NS(message=NS(content=text, tool_calls=None), finish_reason="stop")])


def test_a_step_goes_through_the_one_door_with_his_account(monkeypatch):
    from browser_use.llm.messages import SystemMessage, UserMessage
    seen = []

    def call(what, messages, **kw):
        seen.append((what, messages, kw))
        return _answer(json.dumps({"thinking": "fill the name", "action": "input"}))
    monkeypatch.setattr(background, "call", call)
    llm = browser_llm.SandyLLM(user_id="userA")
    got = asyncio.run(llm.ainvoke([SystemMessage(content="be careful"), UserMessage(content="page")], Step))
    assert got.completion == Step(thinking="fill the name", action="input")
    [(what, messages, kw)] = seen
    assert what == "browser_step" and kw["priority"] == background.DIRECT and kw["user_id"] == "userA"
    assert messages[0] == {"role": "system", "content": "be careful"}
    assert kw["response_format"]["type"] == "json_schema"


def test_plain_text_comes_back_as_text(monkeypatch):
    from browser_use.llm.messages import UserMessage
    monkeypatch.setattr(background, "call", lambda *a, **kw: _answer("done"))
    got = asyncio.run(browser_llm.SandyLLM(user_id="u").ainvoke([UserMessage(content="x")]))
    assert got.completion == "done"


@pytest.mark.parametrize("fail", [RuntimeError("no model"), "not json"])
def test_a_failure_is_the_providers_error(monkeypatch, fail):
    from browser_use.llm.exceptions import ModelProviderError
    from browser_use.llm.messages import UserMessage

    def call(*a, **kw):
        if isinstance(fail, Exception):
            raise fail
        return _answer(fail)
    monkeypatch.setattr(background, "call", call)
    with pytest.raises(ModelProviderError):
        asyncio.run(browser_llm.SandyLLM(user_id="u").ainvoke([UserMessage(content="x")], Step))


def test_it_is_a_model_browser_use_accepts():
    from browser_use.llm.base import BaseChatModel
    llm = browser_llm.SandyLLM(user_id="u")
    assert isinstance(llm, BaseChatModel) and llm.provider == "sandy" and llm.name == "sandy"
