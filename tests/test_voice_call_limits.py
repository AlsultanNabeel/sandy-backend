"""A call ends by itself: after a stretch with nobody talking, and at a hard maximum.

Before, a call streaming silence (or a TV) stayed open for as long as the socket did:
the keepalive kept it up and every GoAway reconnected it, paying Gemini by the minute.
These run the real `_live_session` with a fake socket and a fake Gemini.
"""
from __future__ import annotations

import asyncio
import json
import math
import struct
import time

import pytest

pytest.importorskip("google.genai")


def _silence() -> bytes:
    return b"\x00\x00" * 640                       # 40 ms


def _voice() -> bytes:
    """40 ms of a 180 Hz tone, loud: what the VAD calls speech and _voiced calls a voice."""
    return b"".join(struct.pack("<h", int(4000 * math.sin(2 * math.pi * 180 * n / 16000)))
                    for n in range(640))


class _Socket:
    """A device that keeps streaming one kind of frame, forty milliseconds apart."""

    environ: dict = {}

    def __init__(self, frame: bytes):
        self.frame = frame
        self.sent = []

    def receive(self, timeout=None):
        time.sleep(0.04)
        return self.frame

    def send(self, data):
        self.sent.append(data)

    def errors(self):
        out = []
        for d in self.sent:
            if isinstance(d, str) and d.startswith("{"):
                msg = json.loads(d)
                if msg.get("type") == "error":
                    out.append(msg.get("msg"))
        return out


class _Gemini:
    """Takes audio, never answers."""

    async def send_realtime_input(self, **kw):
        return None

    async def send_client_content(self, **kw):
        return None

    async def receive(self):
        await asyncio.sleep(3600)
        yield None


class _Manager:
    async def __aexit__(self, *a):
        return None


@pytest.fixture()
def live(monkeypatch):
    from app.api.voice_ws import session as sess

    monkeypatch.setattr("app.config.GEMINI_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(sess, "_build_cached_instruction", lambda who, channel=None: "تعليمات")
    monkeypatch.setattr(sess, "resolve_speaker_label", lambda who: "سامي")
    monkeypatch.setattr(sess, "load_recent_turns", lambda who: [])
    monkeypatch.setattr(sess, "speaker_gate", lambda who, channel: False)
    monkeypatch.setattr(sess, "session_context_for", lambda *a: "")
    monkeypatch.setattr(sess, "remember_live_model", lambda name: None)

    async def _open(client, config):
        return _Manager(), _Gemini(), "fake-live", None
    monkeypatch.setattr(sess, "_open_live_session", _open)

    def run(ws, idle_s, max_s, within_s):
        monkeypatch.setattr(sess, "_CALL_IDLE_S", idle_s)
        monkeypatch.setattr(sess, "_CALL_MAX_S", max_s)
        started = time.monotonic()
        asyncio.run(asyncio.wait_for(sess._live_session(ws, "test"), within_s))
        return time.monotonic() - started
    return run


def test_a_call_nobody_talks_in_ends_after_the_quiet_stretch(live):
    ws = _Socket(_silence())
    took = live(ws, idle_s=0.6, max_s=60, within_s=8)
    assert took < 5
    assert ws.errors() == ["call_idle"]


def test_a_call_that_never_stops_ends_at_the_maximum(live):
    ws = _Socket(_voice())
    took = live(ws, idle_s=0.6, max_s=2.0, within_s=10)
    assert 1.5 < took < 8, "someone talking must keep it past the quiet stretch"
    assert ws.errors() == ["call_time_limit"]
