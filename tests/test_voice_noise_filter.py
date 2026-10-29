"""Far talk, the TV and a recogniser's inventions are not turns (voice_ws/noise.py).

The call that would not end: for a quarter of an hour the robot heard the TV, Gemini wrote
it down as «¿Qué?» and «Gracias», and she answered each one in Spanish. Two checks now, in
any language: a voice much quieter than his own level in the call never opens a turn, and a
stock phrase that is the whole of a quiet or very short turn is dropped with its reply.
"""
from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace as NS

import pytest

pytest.importorskip("google.genai")

from app.api.voice_ws import noise  # noqa: E402


def _tone(ms: int, level: float) -> bytes:
    import numpy as np

    t = np.arange(int(16 * ms)) / 16000
    return (level * np.sqrt(2) * np.sin(2 * np.pi * 160 * t)).astype("<i2").tobytes()


# ── The phrases ──

def test_a_stock_phrase_is_an_invention_only_as_the_whole_turn():
    for heard in ("¿Qué?", "Gracias.", "شكراً على المشاهدة", "Thank you for watching!"):
        assert noise.is_invention(heard), heard
    for heard in ("¿Qué hora es?", "gracias por la ayuda", "شكرا كتير يا ساندي", "سكّري"):
        assert not noise.is_invention(heard), heard


def test_a_reply_waits_only_while_the_words_could_still_be_a_stock_phrase():
    assert noise.could_be_invention("")
    assert noise.could_be_invention("Thank you")       # «… for watching» may follow
    assert not noise.could_be_invention("¿Qué hora")
    assert not noise.could_be_invention("ضيفي حليب")


def test_no_language_is_filtered():
    # A real sentence in any language passes, however short or quiet.
    for heard in ("Wie spät ist es?", "今何時ですか", "Quelle heure est-il ?", "kaç saat"):
        assert not noise.is_invention(heard)


def test_far_and_suspect_are_measured_against_his_own_level():
    state: dict = {}
    assert not noise.far(state, 10.0)                 # nothing learned yet: nothing is far
    for lvl in (3000, 3200, 2800):
        noise.learn(state, lvl)
    assert noise.near_level(state) == 3000
    assert noise.far(state, 800) and not noise.far(state, 1500)
    assert noise.suspect(state, 1500, 2000)           # quiet
    assert noise.suspect(state, 3000, 300)            # very short
    assert not noise.suspect(state, 3000, 1200)       # near and long: never dropped


# ── The device side: a far voice opens no turn ──

class _Session:
    def __init__(self):
        self.starts = 0
        self.ends = 0

    async def send_realtime_input(self, **kw):
        if "activity_start" in kw:
            self.starts += 1
        elif "activity_end" in kw:
            self.ends += 1


class _Reader:
    dropped = 0

    def __init__(self, chunks):
        self._chunks = chunks

    def pending(self):
        return 0

    async def frames(self):
        for c in self._chunks:
            yield c


def test_the_tv_under_his_level_opens_no_turn():
    from app.api.voice_ws.session import _device_to_live
    from app.api.voice_ws.speaker import _RecentAudio

    room = [_tone(200, 5)] * 4
    pause = [_tone(200, 5)] * 6
    near = [_tone(200, 3000)] * 4
    tv = [_tone(200, 700)] * 6
    session = _Session()
    state: dict = {}
    asyncio.run(_device_to_live(_Reader(room + near + pause + tv + pause), session,
                                _RecentAudio(), verify=False, live_state=state))
    assert session.starts == 1 and session.ends == 1, "the TV opened a turn"


# ── The live side: an invented turn's reply is never played ──

def _content(**kw):
    base = dict(input_transcription=None, output_transcription=None, interrupted=None,
                model_turn=None, turn_complete=None)
    base.update(kw)
    return NS(server_content=NS(**base), tool_call=None, go_away=None,
              session_resumption_update=None)


class _Live:
    def __init__(self, heard: str):
        self.heard = heard
        self.calls = 0

    async def receive(self):
        self.calls += 1
        if self.calls > 1:
            raise RuntimeError("over")
        yield _content(input_transcription=NS(text=self.heard))
        audio = NS(inline_data=NS(data=b"\x01\x00" * 2400), text=None)
        yield _content(model_turn=NS(parts=[audio]), output_transcription=NS(text="Nada."))
        yield _content(turn_complete=True)


class _Ws:
    def __init__(self):
        self.sent = []

    def send(self, data):
        self.sent.append(data)

    def audio(self):
        return [d for d in self.sent if isinstance(d, (bytes, bytearray))]


def _relay(monkeypatch, heard: str, suspect: bool, language: str = ""):
    from app.api.voice_ws import session as sess
    from app.api.voice_ws.speaker import _RecentAudio

    saved = []
    monkeypatch.setattr(sess, "_save_voice_turn", lambda *a: saved.append(a))
    ws = _Ws()
    state = {"turn_suspect": suspect, **({"lang": language} if language else {})}
    asyncio.run(sess._live_to_device(ws, _Live(heard), _RecentAudio(), state))
    time.sleep(0.1)   # the save runs on an executor
    return ws, state, saved


def test_an_invented_quiet_turn_is_dropped_with_its_reply(monkeypatch):
    ws, state, saved = _relay(monkeypatch, "¿Qué?", suspect=True)
    assert not ws.audio(), "her answer to the TV was played"
    assert not saved, "the invented turn was kept in memory"
    assert "understood_at" not in state, "the invented turn kept the call from ending"
    assert any(json.loads(d).get("type") == "end_turn" for d in ws.sent if isinstance(d, str))


def test_the_same_words_said_close_and_clearly_go_through(monkeypatch):
    ws, state, saved = _relay(monkeypatch, "¿Qué?", suspect=False)
    assert ws.audio() and saved and "understood_at" in state


def test_a_quiet_turn_with_real_words_is_answered(monkeypatch):
    ws, _, saved = _relay(monkeypatch, "¿Qué hora es?", suspect=True)
    assert ws.audio() and saved


# An invented turn is not the call's language: «¿Qué?» from the TV in an Arabic call, or
# «شكراً على المشاهدة» in an English one, left the next tool reply in the other language.
@pytest.mark.parametrize("heard, language", [("¿Qué?", "ar"), ("شكراً على المشاهدة", "en")])
def test_an_invented_turn_does_not_change_the_calls_language(monkeypatch, heard, language):
    _, state, _ = _relay(monkeypatch, heard, suspect=True, language=language)
    assert state["lang"] == language


@pytest.mark.parametrize("heard, before, after", [("¿Qué hora es?", "ar", "en"),
                                                  ("شو الساعة؟", "en", "ar")])
def test_a_real_turn_sets_the_calls_language(monkeypatch, heard, before, after):
    _, state, _ = _relay(monkeypatch, heard, suspect=True, language=before)
    assert state["lang"] == after
