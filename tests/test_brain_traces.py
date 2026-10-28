"""Every turn leaves one trace: chat (brain and fast path), voice tools, the model's tokens
from every call, and a trace that cannot be written never breaks the turn."""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest
from brain_fakes import (A, ScriptedModel, brain_db, call, on_node, text_reply,  # noqa: F401
                         tools_reply)
from cryptography.fernet import Fernet

from app.brain import loop, tools
from app.features import trace_store
from app.integrations import openai_client
from app.utils import ltm_crypto
from app.utils.user_profiles import active_user_profile_context


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setattr(ltm_crypto, "_fernet", Fernet(Fernet.generate_key()))
    monkeypatch.setattr(ltm_crypto, "_init_attempted", True)


def _turn(model, message="ضيفي حليب"):
    with active_user_profile_context(A):
        return loop.run_turn(message, user_id="userA", chat_id="userA", source="web",
                             complete=model)


def _rows(db):
    return list(db[trace_store.COLLECTION].find())


def test_a_chat_turn_leaves_one_trace_with_its_tools(brain_db):  # noqa: F811
    class Counting(ScriptedModel):
        def __call__(self, messages, specs, on_text=None):
            trace_store.note_model_call("azure", "gpt-4.1", tokens_in=500, tokens_out=20, ms=7)
            return super().__call__(messages, specs, on_text)

    _turn(Counting(tools_reply(call("list_add", list="shopping", text="حليب")),
                   text_reply("ضفت الحليب")))
    [row] = _rows(brain_db)
    got = trace_store.get_trace("userA", row["_id"])
    assert got["user_id"] == "userA" and got["source"] == "chat" and got["routed_by"] == "brain"
    assert got["request"] == "ضيفي حليب" and got["reply"] == "ضفت الحليب"
    assert [t["name"] for t in got["tools"]] == ["list_add"]
    assert got["tools"][0]["args"] == {"list": "shopping", "text": "حليب"}
    assert got["tools"][0]["result"]["ok"] is True
    assert len(got["model_calls"]) == 2 and got["tokens_in"] == 1000


def test_tools_run_side_by_side_are_both_traced(brain_db, monkeypatch):  # noqa: F811
    monkeypatch.setitem(tools.HANDLERS, "weather", lambda a, c: {"ok": True, "reply": "شمس"})
    monkeypatch.setitem(tools.HANDLERS, "web_search", lambda a, c: {"ok": True, "reply": "لقيت"})
    _turn(ScriptedModel(tools_reply(call("weather", "c1", city="عمان"),
                                    call("web_search", "c2", query="أخبار")),
                        text_reply("تمام")), "الطقس والأخبار")
    [row] = _rows(brain_db)
    assert sorted(t["name"] for t in row["tools"]) == ["weather", "web_search"]


def test_a_fast_path_turn_is_traced_as_one(brain_db, monkeypatch):  # noqa: F811
    from app.features import device_store
    monkeypatch.setattr("app.integrations.device_publisher.get_device_publisher",
                        lambda: NS(send_to_topic=lambda topic, payload: True))
    with active_user_profile_context(A):
        device_store.add_device("living_light", "الضو", "switch", on_node("light"))
    state = _turn(ScriptedModel(), "شغل الضو")
    assert state["routed_by"] == "fast_path"
    [row] = _rows(brain_db)
    assert row["routed_by"] == "fast_path" and row["model_calls"] == []


def test_a_trace_that_cannot_be_written_never_breaks_the_turn(brain_db, monkeypatch):  # noqa: F811
    monkeypatch.setattr(trace_store, "_collection", lambda user_id: 1 / 0)
    state = _turn(ScriptedModel(text_reply("أهلين")), "مرحبا")
    assert state["final_response"] == "أهلين" and state["error"] is None


def test_a_voice_tool_is_traced_into_the_calls_turn(brain_db):  # noqa: F811
    from app.api.voice_ws.tools import _dispatch_tool

    t = trace_store.Trace("userA", "voice")
    _dispatch_tool("list_add", {"list": "shopping", "text": "خبز"}, "userA", "turn1", trace=t)
    assert [x["name"] for x in t.tools] == ["list_add"]


def test_a_voice_turn_is_one_model_call_its_context_counted_once():
    """Each live message reports the whole context in its details: billed once a turn."""
    t = trace_store.Trace("userA", "voice")
    for whole in (900, 1200, 1100):
        trace_store.note_live_usage(t, "gemini-live", NS(
            prompt_token_count=25, response_token_count=10, cached_content_token_count=None,
            prompt_tokens_details=[NS(modality="AUDIO", token_count=whole - 100),
                                   NS(modality="TEXT", token_count=100)]))
    trace_store.note_live_usage(t, "gemini-live", None)
    [c] = t.model_calls
    assert (c["provider"], c["tokens_in"], c["tokens_out"]) == ("gemini", 1200, 30)


def test_without_details_the_top_level_count_is_used():
    t = trace_store.Trace("userA", "voice")
    trace_store.note_live_usage(t, "gemini-live", NS(prompt_token_count=300,
                                                     response_token_count=7,
                                                     prompt_tokens_details=None,
                                                     cached_content_token_count=None))
    assert t.model_calls[0]["tokens_in"] == 300


# ── the tokens of every model call, at the one client ──────────────────────

def _client(resp):
    return NS(chat=NS(completions=NS(create=lambda **kw: resp(kw))))


def test_a_plain_call_reports_its_tokens():
    usage = NS(prompt_tokens=120, completion_tokens=30,
               prompt_tokens_details=NS(cached_tokens=100))
    t = trace_store.Trace("u", "chat")
    with trace_store.using(t):
        openai_client.create_chat_completion(
            [{"role": "user", "content": "x"}], openai_client=None,
            azure_openai_client=_client(lambda kw: NS(usage=usage, choices=[])),
            azure_chat_deployment="gpt-4.1")
    [c] = t.model_calls
    assert (c["provider"], c["model"], c["tokens_in"], c["tokens_out"], c["tokens_cached"]) == \
        ("azure", "gpt-4.1", 120, 30, 100)


def test_a_streamed_call_asks_for_its_tokens_and_reports_them():
    sent = {}

    def resp(kw):
        sent.update(kw)
        return iter([NS(choices=[NS(delta=NS(content="أ", tool_calls=None))], usage=None),
                     NS(choices=[], usage=NS(prompt_tokens=80, completion_tokens=5,
                                             prompt_tokens_details=None))])
    t = trace_store.Trace("u", "chat")
    with trace_store.using(t):
        out = openai_client.create_chat_completion(
            [{"role": "user", "content": "x"}], openai_client=_client(resp), stream=True,
            openai_model="gpt-4.1-mini")
        assert len(list(out)) == 2
    assert sent["stream_options"] == {"include_usage": True}
    [c] = t.model_calls
    assert (c["provider"], c["tokens_in"], c["tokens_out"]) == ("openai", 80, 5)


def test_the_direct_fallback_reports_its_tokens(monkeypatch):
    from app.brain import model
    usage = NS(prompt_tokens=40, completion_tokens=4, prompt_tokens_details=None)
    fake = _client(lambda kw: NS(usage=usage, choices=[NS(message=NS(content="هاي",
                                                                       tool_calls=None))]))
    monkeypatch.setattr(model, "openai_direct_client", lambda: fake)
    t = trace_store.Trace("u", "chat")
    with trace_store.using(t):
        model._openai_direct([{"role": "user", "content": "x"}], [])
    assert [(c["provider"], c["tokens_in"]) for c in t.model_calls] == [("openai", 40)]
