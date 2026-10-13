"""«سكّري» hangs up: the robot's call has a tool that ends it, and she may not say it ended
otherwise.

Before, nothing could end a call from the conversation. Told «سكّري المكالمة», she answered
«سكّرت المكالمة» and the call went on for minutes, answering the TV. These run the real
`_live_session` with a fake socket and a fake Gemini that calls the tool.
"""
from __future__ import annotations

import asyncio
import json
import math
import struct
import time
from types import SimpleNamespace as NS

import pytest

pytest.importorskip("google.genai")


def _voice() -> bytes:
    return b"".join(struct.pack("<h", int(4000 * math.sin(2 * math.pi * 180 * n / 16000)))
                    for n in range(640))


class _Socket:
    environ: dict = {}

    def __init__(self):
        self.sent = []

    def receive(self, timeout=None):
        time.sleep(0.04)
        return _voice()

    def send(self, data):
        self.sent.append(data)

    def frames(self):
        return [json.loads(d) for d in self.sent if isinstance(d, str) and d.startswith("{")]


def _content(**kw):
    base = dict(input_transcription=None, output_transcription=None, interrupted=None,
                model_turn=None, turn_complete=None)
    base.update(kw)
    return NS(server_content=NS(**base), tool_call=None, go_away=None,
              session_resumption_update=None)


class _Gemini:
    """Calls `end_call` once, says a one-second goodbye after the answer, then nothing."""

    def __init__(self):
        self.answered = asyncio.Event()
        self.tool_answers = []
        self.turns = 0

    async def send_realtime_input(self, **kw):
        return None

    async def send_client_content(self, **kw):
        return None

    async def send_tool_response(self, function_responses):
        self.tool_answers.extend(function_responses)
        self.answered.set()

    async def receive(self):
        self.turns += 1
        if self.turns > 1:
            await asyncio.sleep(3600)
        yield NS(server_content=None, go_away=None, session_resumption_update=None,
                 tool_call=NS(function_calls=[NS(id="1", name="end_call", args={})]))
        await self.answered.wait()
        audio = NS(inline_data=NS(data=b"\x00\x00" * 24000), text=None)   # one second
        yield _content(model_turn=NS(parts=[audio]),
                       output_transcription=NS(text="يلا باي"))
        yield _content(turn_complete=True)


class _Manager:
    async def __aexit__(self, *a):
        return None


@pytest.fixture()
def call(monkeypatch):
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
    monkeypatch.setattr(sess, "_CALL_IDLE_S", 60.0)
    sess.set_voice_identity("u1")
    sess.set_voice_channel(sess._ROBOT_CHANNEL)
    gemini = _Gemini()

    async def _open(client, config):
        gemini.config = config
        return _Manager(), gemini, "fake-live", None
    monkeypatch.setattr(sess, "_open_live_session", _open)
    yield sess, gemini
    sess.set_voice_identity("")
    sess.set_voice_channel("")


def test_end_call_hangs_up_after_her_goodbye_has_played(call):
    sess, gemini = call
    ws = _Socket()
    started = time.monotonic()
    asyncio.run(asyncio.wait_for(sess._live_session(ws, "test"), 10))
    took = time.monotonic() - started
    # The one-second goodbye is waited for, then the socket closes cleanly: no error frame,
    # which is what the board reads as «the server closed the call».
    assert 1.0 <= took < 6, took
    assert not [f for f in ws.frames() if f.get("type") == "error"]
    assert gemini.tool_answers and "بتسكّر" in gemini.tool_answers[0].response["output"]
    names = [d.name for t in gemini.config.tools for d in t.function_declarations]
    assert "end_call" in names


def test_only_the_robot_is_given_the_tool():
    from app.brain import voice

    assert voice.END_CALL in [d["name"] for d in voice.declarations(end_call=True)]
    assert voice.END_CALL not in [d["name"] for d in voice.declarations()]


def test_she_is_told_only_the_tool_ends_a_call():
    from app.api.voice_ws import memory

    memory.set_voice_channel("الروبوت")
    robot = memory._channel_line()
    memory.set_voice_channel("مكالمة التطبيق")
    app = memory._channel_line()
    memory.set_voice_channel("")
    assert "end_call" in robot and "ممنوع تقولي «سكّرت» إلا لما الأداة تشتغل" in robot
    assert "اسأليه" in robot                       # unclear: she asks
    assert "زر الإنهاء" in app and "end_call" not in app


def test_a_goodbye_that_never_finishes_still_hangs_up():
    from app.api.voice_ws import session as sess

    async def run():
        state = {"call_deadline": time.monotonic() + 60, "call_started": time.monotonic(),
                 "end_asked_at": time.monotonic() - 2 * sess._GOODBYE_MAX_S}
        await asyncio.wait_for(sess._call_watchdog(state), 3)
        return state

    assert asyncio.run(run())["ended"] == "user_ended"
