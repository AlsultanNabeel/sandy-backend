"""The loop: tool call -> result -> answer, the step cap, streaming, the fast path, STM."""
from __future__ import annotations

import json

from brain_fakes import (A, ScriptedModel, brain_db, call, text_reply,  # noqa: F401
                         tools_reply)

from app.blocks import items
from app.brain import loop
from app.brain.model import Reply, clear_stream_hooks, set_stream_hooks
from app.utils.user_profiles import active_user_profile_context


def _turn(model, message="ضيفي حليب", pending=None):
    with active_user_profile_context(A):
        return loop.run_turn(message, user_id="userA", chat_id="userA", source="web",
                             pending_state=pending, complete=model)


def test_tool_call_then_result_then_answer(brain_db):  # noqa: F811
    model = ScriptedModel(tools_reply(call("list_add", list="shopping", text="حليب")),
                          text_reply("ضفت الحليب لقائمة التسوق"))
    state = _turn(model)
    assert state["final_response"] == "ضفت الحليب لقائمة التسوق"
    assert state["tools_used"] == ["list_add"]
    with active_user_profile_context(A):
        assert [i["text"] for i in items.list_items("shopping")] == ["حليب"]
    # The second call saw the tool's result as a tool message tied to the call id.
    tool_msg = model.seen[1][-1]
    assert tool_msg["role"] == "tool" and tool_msg["tool_call_id"] == "c1"
    assert json.loads(tool_msg["content"])["ok"] is True
    assert model.seen[1][-2]["tool_calls"][0]["function"]["name"] == "list_add"


def test_plain_chat_is_one_call(brain_db):  # noqa: F811
    model = ScriptedModel(text_reply("أهلين!"))
    state = _turn(model, "مرحبا")
    assert state["final_response"] == "أهلين!" and len(model.seen) == 1
    system = model.seen[0][0]
    assert system["role"] == "system" and "الآن:" in system["content"]


def test_iteration_cap_is_six_model_calls(brain_db):  # noqa: F811
    model = ScriptedModel(*[tools_reply(call("recall", cid=f"c{i}", query="x"))
                            for i in range(10)])
    state = _turn(model, "دوري")
    assert len(model.seen) == loop.MAX_STEPS == 6
    assert state["final_response"] == loop.GAVE_UP_REPLY


def test_model_down_gives_the_error_sentence(brain_db):  # noqa: F811
    state = _turn(lambda m, t, on_text=None: None, "مرحبا")
    assert state["final_response"] == loop.ERROR_REPLY and state["error"]


def test_the_final_text_streams_through_the_hooks(brain_db):  # noqa: F811
    chunks = []
    set_stream_hooks(on_start=lambda: None, on_chunk=chunks.append)
    try:
        _turn(ScriptedModel(text_reply("مرحبا فيك")), "هاي")
    finally:
        clear_stream_hooks()
    assert chunks and chunks[-1] == "مرحبا فيك"


def test_each_tool_is_announced_before_it_runs(brain_db):  # noqa: F811
    steps = []
    set_stream_hooks(on_start=lambda: None, on_chunk=lambda c: None, on_step=steps.append)
    try:
        _turn(ScriptedModel(tools_reply(call("list_add", list="shopping", text="حليب")),
                            text_reply("ضفته")))
    finally:
        clear_stream_hooks()
    assert steps == ["list_add"]


def test_the_turn_is_written_to_short_term_memory(brain_db):  # noqa: F811
    _turn(ScriptedModel(text_reply("تمام")), "كيفك")
    from app.brain.stm import recent_turns_for_user
    turns = recent_turns_for_user("userA")
    assert [t["content"] for t in turns] == ["كيفك", "تمام"]
    # ...and the next turn sees it as history.
    model = ScriptedModel(text_reply("اه"))
    _turn(model, "شو حكيت؟")
    assert {"role": "assistant", "content": "تمام"} in model.seen[0]


def test_fast_path_still_wins_with_no_model_call(brain_db, monkeypatch):  # noqa: F811
    from app.features import device_store
    sent = {}

    class _Client:
        def send_to_topic(self, topic, payload):
            sent[topic] = payload
            return True

    monkeypatch.setattr("app.integrations.room_device.get_room_device_client", lambda: _Client())
    with active_user_profile_context(A):
        device_store.add_device("living_light", "الضو", "switch",
                                {"kind": "mqtt", "topic": "room/cmd/light"})
    model = ScriptedModel()
    state = _turn(model, "شغل الضو")
    assert model.seen == [] and sent == {"room/cmd/light": "on"}
    assert state["routed_by"] == "fast_path" and "شغّلت" in state["final_response"]


def test_fast_path_steps_aside_while_a_confirmation_is_held(brain_db):  # noqa: F811
    from app.brain import confirm
    held = confirm.hold("list_update", {"id": "x", "delete": True}, "تحذف «x»")
    model = ScriptedModel(text_reply("تمام"))
    state = _turn(model, "لا", pending=held)
    assert state["final_response"] == confirm.CANCELLED_REPLY and model.seen == []


def test_image_bytes_reach_the_reply(brain_db, monkeypatch):  # noqa: F811
    def fake_image(args, ctx):
        ctx.artifacts["image_bytes"] = b"png"
        return {"ok": True, "reply": "تفضل"}

    monkeypatch.setitem(loop.tools.HANDLERS, "image", fake_image)
    state = _turn(ScriptedModel(tools_reply(call("image", prompt="قطة")),
                                Reply(text="هاي الصورة")), "ارسمي قطة")
    assert state["execution_result"]["image_bytes"] == b"png"


def test_she_knows_it_is_a_chat_and_answers_in_the_messages_language(brain_db):  # noqa: F811
    from app.brain import context
    model = ScriptedModel(text_reply("hi"))
    _turn(model, "how are you today?")
    system = model.seen[0][0]["content"]
    assert context.CHAT_CHANNEL in system and context.SPOKEN_CHANNEL not in system
    assert system.endswith(context.reply_language("how are you today?"))
    assert "English" in context.reply_language("ok remind me at 5 please")
    assert "بالعربي" in context.reply_language("ذكريني بالـ meeting")


def test_a_spoken_turn_is_told_it_is_heard(brain_db):  # noqa: F811
    from app.brain import context
    model = ScriptedModel(text_reply("أهلين"))
    with active_user_profile_context(A):
        loop.run_turn("مرحبا", user_id="userA", chat_id="userA", source="voice", complete=model)
    assert context.SPOKEN_CHANNEL in model.seen[0][0]["content"]
