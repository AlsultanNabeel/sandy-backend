"""A reply never says she deleted, added, changed or cancelled something unless a tool
did it in the same turn: checked by the server, on chat and voice alike, not left to the
prompt. On 19 Oct 2026 she said «حذفت» four times when nothing had been deleted."""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace as NS

import pytest
from brain_fakes import A, ScriptedModel, brain_db, call, text_reply, tools_reply  # noqa: F401

from app.blocks import items
from app.brain import honesty, lang, loop
from app.utils.user_profiles import active_user_profile_context


def _turn(model, message, pending=None):
    with active_user_profile_context(A):
        return loop.run_turn(message, user_id="userA", chat_id="userA", source="web",
                             pending_state=pending, complete=model)


def _milk():
    with active_user_profile_context(A):
        return items.add("shopping", "حليب")


@pytest.mark.parametrize("text, kinds", [
    ("شلت الحليب من القائمة ✅", {"delete"}),
    ("تمام، وحذفتها كمان", {"delete"}),
    ("ضفت خبز للتسوق", {"add"}),
    ("عدّلت الموعد لبكرا", {"edit"}),
    ("لغيت تذكير الدوا", {"cancel"}),
    ("ما حذفت إشي، ما لقيت الحليب", set()),
    ("لسا ما ضفته", set()),
    ("بدك أحذف الحليب؟", set()),
    ("الجو حلو اليوم", set()),
])
def test_what_a_sentence_claims(text, kinds):
    assert honesty.claims(text) == kinds


def test_a_claim_with_no_tool_is_replaced(brain_db):  # noqa: F811
    milk = _milk()
    state = _turn(ScriptedModel(text_reply("شلت الحليب من القائمة ✅")), "شيلي الحليب من القائمة")
    assert "شلت" not in state["final_response"]
    assert state["final_response"] == lang.PHRASES["nothing_done"]["ar"]
    with active_user_profile_context(A):
        assert items.get(milk) is not None


def test_a_claim_after_a_tool_that_found_nothing_says_what_the_tool_said(brain_db):  # noqa: F811
    model = ScriptedModel(tools_reply(call("list_delete", list="shopping", match_text="حليب")),
                          text_reply("شلت الحليب ✅"))
    state = _turn(model, "شيلي الحليب")
    assert state["final_response"].startswith("ما لقيت «حليب»")


def test_a_claim_after_a_tool_that_did_it_stays(brain_db):  # noqa: F811
    milk = _milk()
    model = ScriptedModel(tools_reply(call("list_delete", id=milk)), text_reply("شلت الحليب ✅"))
    assert _turn(model, "شيلي الحليب")["final_response"] == "شلت الحليب ✅"


def test_the_wrong_kind_of_tool_does_not_back_a_claim(brain_db):  # noqa: F811
    model = ScriptedModel(tools_reply(call("list_add", list="shopping", text="خبز")),
                          text_reply("ضفت الخبز وحذفت الحليب"))
    state = _turn(model, "ضيفي خبز وشيلي الحليب")
    assert "حذفت" not in state["final_response"] and "«خبز»" in state["final_response"]


def test_an_answer_beside_a_false_claim_is_kept(brain_db):  # noqa: F811
    model = ScriptedModel(text_reply("شلت الحليب.\nوبكرا عندك اجتماع الساعة عشرة."))
    state = _turn(model, "شيلي الحليب وشو عندي بكرا؟")
    assert "شلت" not in state["final_response"]
    assert "بكرا عندك اجتماع الساعة عشرة" in state["final_response"]


def test_a_held_bulk_delete_is_never_said_to_be_done(brain_db):  # noqa: F811
    with active_user_profile_context(A):
        ids = [items.add("tasks", f"جيم {n}") for n in range(6)]
    model = ScriptedModel(tools_reply(call("list_delete", list="tasks", match_text="جيم",
                                           all_matching=True)), text_reply("حذفتهم كلهم ✅"))
    state = _turn(model, "احذفي كل مهام الجيم")
    assert "حذفتهم" not in state["final_response"]
    assert state["final_response"].startswith("متأكد إنك بدك تحذف")
    assert state["pending_state"] is not None
    with active_user_profile_context(A):
        assert all(items.get(i) for i in ids)


# ── voice: what she said is heard already, so she is told to put it right ─────

class _Socket:
    environ: dict = {}

    def __init__(self):
        self.sent = []

    def receive(self, timeout=None):
        time.sleep(0.04)
        return b"\x00\x00" * 640

    def send(self, data):
        self.sent.append(data)


def _content(**kw):
    base = dict(input_transcription=None, output_transcription=None, interrupted=None,
                model_turn=None, turn_complete=None)
    base.update(kw)
    return NS(server_content=NS(**base), tool_call=None, go_away=None,
              session_resumption_update=None)


class _Gemini:
    """One turn: optionally a tool call, then «حذفت الحليب» and the turn's end."""

    def __init__(self, tool=None):
        self.tool = tool
        self.notes = []
        self.answered = asyncio.Event()
        self.done = asyncio.Event()
        self.turns = 0

    async def send_realtime_input(self, **kw):
        return None

    async def send_client_content(self, **kw):
        self.notes.append(kw)

    async def send_tool_response(self, function_responses):
        self.answered.set()

    async def receive(self):
        self.turns += 1
        if self.turns > 1:
            self.done.set()
            await asyncio.sleep(3600)
        if self.tool:
            yield NS(server_content=None, go_away=None, session_resumption_update=None,
                     tool_call=NS(function_calls=[NS(id="1", name=self.tool[0], args=self.tool[1])]))
            await self.answered.wait()
        yield _content(input_transcription=NS(text="شيلي الحليب"))
        yield _content(output_transcription=NS(text="حذفت الحليب من القائمة"))
        yield _content(turn_complete=True)


class _Manager:
    async def __aexit__(self, *a):
        return None


def _call(monkeypatch, gemini):
    pytest.importorskip("google.genai")
    from app.api.voice_ws import session as sess

    monkeypatch.setattr("app.config.GEMINI_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(sess, "_build_cached_instruction", lambda who, channel=None: "تعليمات")
    monkeypatch.setattr(sess, "resolve_speaker_label", lambda who: "سامي")
    monkeypatch.setattr(sess, "load_recent_turns", lambda who: [])
    monkeypatch.setattr(sess, "speaker_gate", lambda who, channel: False)
    monkeypatch.setattr(sess, "session_context_for", lambda *a: "")
    monkeypatch.setattr(sess, "remember_live_model", lambda name: None)
    monkeypatch.setattr(sess, "voice_seconds_left", lambda who: 3600.0)
    monkeypatch.setattr(sess, "add_voice_seconds", lambda who, s: None)
    monkeypatch.setattr(sess, "_save_voice_turn", lambda *a: None)

    async def _open(client, config):
        return _Manager(), gemini, "fake-live", None
    monkeypatch.setattr(sess, "_open_live_session", _open)
    sess.set_voice_identity("userA")
    sess.set_voice_channel("مكالمة التطبيق")

    async def run():
        task = asyncio.ensure_future(sess._live_session(_Socket(), "test"))
        await asyncio.wait_for(gemini.done.wait(), 5)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001 — the call is torn down
            pass
    try:
        asyncio.run(run())
    finally:
        sess.set_voice_identity("")
        sess.set_voice_channel("")
    return [n for n in gemini.notes if n.get("turn_complete")]


def test_voice_a_claim_with_no_tool_is_put_right(monkeypatch, brain_db):  # noqa: F811
    notes = _call(monkeypatch, _Gemini())
    assert len(notes) == 1
    said = notes[0]["turns"][0].parts[0].text
    assert "ما انعمل" in said


def test_voice_a_claim_after_the_tool_did_it_stands(monkeypatch, brain_db):  # noqa: F811
    milk = _milk()
    assert _call(monkeypatch, _Gemini(tool=("list_delete", {"id": milk}))) == []
    with active_user_profile_context(A):
        assert items.get(milk) is None
