"""The chat on Azure's Responses API (`brain/responses.py`): the same turn as on chat
completions, nothing kept at Azure, the sealed reasoning handed back on the next step, and
chat completions when it fails."""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest
from brain_fakes import A, brain_db  # noqa: F401

from app.brain import loop, model, responses
from app.integrations import openai_client
from app.utils.user_profiles import active_user_profile_context


class _Item(NS):
    def model_dump(self, exclude_none=True):
        return {k: v for k, v in vars(self).items() if v is not None and k != "content"} | (
            {"content": [vars(p) for p in self.content]} if getattr(self, "content", None) else {})


def _call(name, call_id, args):
    return _Item(type="function_call", call_id=call_id, name=name, arguments=args, id="fc_" + call_id)


def _thought():
    return _Item(type="reasoning", id="rs_1", encrypted_content="SEALED", summary=[])


def _text(text):
    return _Item(type="message", role="assistant", id="msg_1",
                 content=[NS(type="output_text", text=text)])


def _response(*output, thought=7):
    return NS(output=list(output), model="gpt-6-luna",
              usage=NS(input_tokens=100, output_tokens=30,
                       input_tokens_details=NS(cached_tokens=10),
                       output_tokens_details=NS(reasoning_tokens=thought)))


@pytest.fixture
def azure(monkeypatch):
    """A Responses API that answers from a script and keeps every request it was sent."""
    sent, script = [], []
    monkeypatch.setattr(openai_client, "responses_client", lambda: object())

    def create(**kw):
        sent.append(kw)
        return script.pop(0)
    monkeypatch.setattr(openai_client, "create_response", create)
    return sent, script


def _turn(message):
    with active_user_profile_context(A):
        return loop.run_turn(message, user_id="userA", chat_id="userA", source="web",
                             complete=responses.complete)


@pytest.mark.parametrize("message, item, said", [
    ("ضيفي حليب", "حليب", "ضفت الحليب ✅"),
    ("add milk", "milk", "Added the milk ✅"),
])
def test_a_tool_turn_hands_the_sealed_reasoning_back_and_keeps_nothing(brain_db, azure,  # noqa: F811
                                                                       message, item, said):
    sent, script = azure
    script += [_response(_thought(), _call("list_add", "c1", f'{{"list": "shopping", "text": "{item}"}}')),
               _response(_text(said))]
    assert _turn(message)["final_response"] == said
    first, second = sent
    for kw in sent:
        assert kw["store"] is False and kw["include"] == ["reasoning.encrypted_content"]
        assert kw["reasoning"] == {"effort": "low"} and kw["max_output_tokens"] == 2000
        assert "temperature" not in kw
    assert {t["name"] for t in first["tools"]} >= {"list_add"} and "function" not in first["tools"][0]
    handed = second["input"]
    assert {"type": "reasoning", "id": "rs_1", "encrypted_content": "SEALED", "summary": []} in handed
    out = next(i for i in handed if i.get("type") == "function_call_output")
    assert out["call_id"] == "c1" and '"ok": true' in out["output"]


def test_a_streamed_answer_arrives_cumulatively(azure):
    sent, script = azure
    done = _response(_text("Hello there"))
    script.append(iter([NS(type="response.output_text.delta", delta="Hello"),
                        NS(type="response.output_text.delta", delta=" there"),
                        NS(type="response.completed", response=done)]))
    seen = []
    assert responses.complete([{"role": "user", "content": "hi"}], [], on_text=seen.append).text == "Hello there"
    assert seen == ["Hello", "Hello there"] and sent[0]["stream"] is True


def test_its_failure_goes_on_on_chat_completions(monkeypatch, azure):
    from openai import APIConnectionError
    monkeypatch.setattr(openai_client, "create_response",
                        lambda **kw: (_ for _ in ()).throw(APIConnectionError(request=NS())))
    monkeypatch.setattr(model, "complete", lambda m, t, on_text=None: model.Reply(text="from chat"))
    assert responses.complete([{"role": "user", "content": "hi"}], []).text == "from chat"


def test_with_no_deployment_set_it_is_chat_completions(monkeypatch):
    monkeypatch.setattr(openai_client, "responses_client", lambda: None)
    monkeypatch.setattr(model, "complete", lambda m, t, on_text=None: model.Reply(text="from chat"))
    assert responses.complete([{"role": "user", "content": "hi"}], []).text == "from chat"


def test_its_thinking_is_its_own_column_in_the_trace(azure):
    from app.features import trace_store
    _, script = azure
    script.append(_response(_text("ok"), thought=42))
    trace = trace_store.Trace("userA", "chat")
    with trace_store.using(trace):
        responses.complete([{"role": "user", "content": "hi"}], [])
    assert trace.model_calls == [{"provider": "azure", "model": "gpt-6-luna", "tokens_in": 100,
                                  "tokens_out": 30, "tokens_cached": 10, "tokens_reasoning": 42,
                                  "ms": trace.model_calls[0]["ms"]}]


def test_what_only_it_reads_never_reaches_chat_completions(monkeypatch):
    seen = []
    monkeypatch.setattr(model, "_primary", lambda m, t, stream: seen.append(m) or NS(
        choices=[NS(message=NS(content="ok", tool_calls=None))]))
    model.complete([{"role": "assistant", "content": None, "tool_calls": [], "_items": [{"x": 1}]}], [])
    assert "_items" not in seen[0][0]


# Behind its switch (`responses_api`), on for the owner's account first: everyone else stays
# on chat completions until he says so.
@pytest.mark.parametrize("user, path", [("userA", "responses"), ("userB", "chat")])
def test_the_switch_picks_the_path_by_account(brain_db, monkeypatch, user, path):  # noqa: F811
    monkeypatch.setenv("SANDY_FLAGS", '{"responses_api": ["userA"]}')
    asked = []
    monkeypatch.setattr(responses, "complete",
                        lambda m, t, on_text=None: asked.append("responses") or model.Reply(text="ok"))
    monkeypatch.setattr(model, "complete",
                        lambda m, t, on_text=None: asked.append("chat") or model.Reply(text="ok"))
    with active_user_profile_context(A):
        loop.run_turn("hello there", user_id=user, chat_id=user, source="web")
    assert asked and set(asked) == {path}
