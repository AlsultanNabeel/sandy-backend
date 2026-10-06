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
    # A paired account with the day's minutes ahead of it; `minutes` below narrows them.
    monkeypatch.setattr(sess, "voice_seconds_left", lambda who: 3600.0)
    monkeypatch.setattr(sess, "add_voice_seconds", lambda who, s: None)
    sess.set_voice_identity("u1")

    async def _open(client, config):
        return _Manager(), _Gemini(), "fake-live", None
    monkeypatch.setattr(sess, "_open_live_session", _open)

    def run(ws, idle_s, max_s, within_s):
        monkeypatch.setattr(sess, "_CALL_IDLE_S", idle_s)
        monkeypatch.setattr(sess, "_CALL_MAX_S", max_s)
        started = time.monotonic()
        asyncio.run(asyncio.wait_for(sess._live_session(ws, "test"), within_s))
        return time.monotonic() - started
    yield run
    sess.set_voice_identity("")


def test_a_board_nobody_paired_gets_no_call(live, monkeypatch):
    """No account to count against: refused before Gemini opens, and the board says so."""
    from app.api.voice_ws import session as sess

    sess.set_voice_identity("")
    opened = []

    async def _never(client, config):
        opened.append(True)
        raise AssertionError("an unpaired board must not open a paid call")
    monkeypatch.setattr(sess, "_open_live_session", _never)
    ws = _Socket(_voice())
    took = live(ws, idle_s=30, max_s=60, within_s=8)
    assert ws.errors() == ["not_paired"]
    assert not opened and took < 2


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


# ── Minutes a day (H6) ───────────────────────────────────────────────────────

@pytest.fixture()
def minutes(live, monkeypatch):
    """The live harness, with the day's minutes left (`.left`) and what got recorded (`.used`)."""
    from app.api.voice_ws import session as sess

    class _Day:
        left = 0.0
        used: list = []

        def __call__(self, *a, **k):
            return live(*a, **k)

    day = _Day()
    day.used = []
    monkeypatch.setattr(sess, "voice_seconds_left", lambda who: day.left)
    monkeypatch.setattr(sess, "add_voice_seconds", lambda who, s: day.used.append((who, s)))
    monkeypatch.setattr("app.utils.thread_pool.submit_background",
                        lambda fn, *a, _label=None, **k: fn(*a, **k))
    return day


def test_no_minutes_left_means_no_call(minutes):
    minutes.left = 0
    ws = _Socket(_voice())
    took = minutes(ws, idle_s=30, max_s=60, within_s=5)
    assert took < 3
    assert ws.errors() == ["call_minutes_exceeded"]


def test_a_call_ends_when_the_day_s_minutes_run_out_and_they_are_counted(minutes):
    minutes.left = 1.5
    ws = _Socket(_voice())
    took = minutes(ws, idle_s=30, max_s=60, within_s=8)
    assert ws.errors() == ["call_minutes_exceeded"]
    assert took < 6
    (who, seconds), = minutes.used
    assert who == "u1" and 1.0 < seconds < 6


def test_the_day_s_minutes_and_the_tiers(monkeypatch):
    import mongomock

    from app import db as appdb
    from app.api import metering
    from app.features import usage_store, users_store

    appdb.configure(mongomock.MongoClient().db)
    try:
        monkeypatch.setattr(users_store, "is_subscriber", lambda uid: uid == "paid")
        free = metering.voice_seconds_left("free")
        assert free == metering.CALL_MINUTES_FREE * 60
        assert metering.voice_seconds_left("paid") == metering.CALL_MINUTES_SUBSCRIBER * 60
        assert metering.CALL_MINUTES_SUBSCRIBER > metering.CALL_MINUTES_FREE
        usage_store.add_voice_seconds("free", 90)
        assert metering.voice_seconds_left("free") == free - 90
        usage_store.add_voice_seconds("free", free)
        assert metering.voice_seconds_left("free") == 0
    finally:
        appdb.reset()


def test_the_owner_s_cap_follows_the_account_not_the_sign_in(monkeypatch):
    """The account marked in SANDY_OWNER_ACCOUNTS gets the top cap, even signed in by email."""
    import mongomock

    from app import db as appdb
    from app.api import metering
    from app.features import users_store

    appdb.configure(mongomock.MongoClient().db)
    try:
        monkeypatch.setattr(users_store, "is_subscriber", lambda uid: False)
        monkeypatch.setattr("app.config.SANDY_OWNER_ACCOUNTS", " boss1 , ")
        assert metering.voice_seconds_left("boss1") == metering.CALL_MINUTES_SUBSCRIBER * 60
        assert metering.voice_seconds_left("other") == metering.CALL_MINUTES_FREE * 60
        assert not metering.is_owner_account("")
        monkeypatch.setattr("app.config.SANDY_OWNER_ACCOUNTS", "")
        assert metering.voice_seconds_left("boss1") == metering.CALL_MINUTES_FREE * 60
    finally:
        appdb.reset()


def test_reading_a_reply_aloud_spends_the_same_minutes(monkeypatch):
    import io
    import wave

    import mongomock

    from app.api import metering
    from app.api.server import create_app
    from app.api.auth_handlers import make_token
    from app.features import usage_store
    from app.integrations import gemini_tts

    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\x00\x00" * 24000 * 3)           # three seconds
    monkeypatch.setattr(gemini_tts, "synthesize_voice_with_gemini",
                        lambda text, mood="neutral": buf.getvalue())
    c = create_app(mongo_db=mongomock.MongoClient().db).test_client()
    h = {"Authorization": f"Bearer {make_token('user', user_id='u1')}"}

    before = metering.voice_seconds_left("u1")
    assert c.post("/api/voice/tts", json={"text": "أهلين"}, headers=h).status_code == 200
    assert metering.voice_seconds_left("u1") == pytest.approx(before - 3, abs=0.01)

    usage_store.add_voice_seconds("u1", before)
    r = c.post("/api/voice/tts", json={"text": "أهلين"}, headers=h)
    assert r.status_code == 429 and r.get_json()["error"] == "call_minutes_exceeded"
