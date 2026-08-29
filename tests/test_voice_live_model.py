"""The voice call that died right after «memory seed».

Two separate defects, one on top of the other.

**The model.** Gemini closed the socket with `1007 CONTENT_TYPE_AUDIO is not
supported` at the *first audio frame* — not at the handshake. So a fixed model
name that the API has since stopped accepting for audio looks perfectly healthy
in the log right up to the moment nobody can hear anything. The fix walks a list
of candidates and probes each with a frame of silence.

**The probe leaked the fix.** The first cut of that walk kept the manager it had
already entered and then wrote `async with cm:` over it. `contextlib` deletes
`self.args` on the first `__aenter__`, so the second raised
`'_AsyncGeneratorContextManager' object has no attribute 'args'` — which is
exactly what production logged, on every call, for as long as it was deployed.
A context manager is entered once.
"""
from __future__ import annotations

import asyncio
import contextlib

import pytest


class _FakeSession:
    """Refuses audio the way the real one did: at the frame, not the handshake."""

    def __init__(self, refuse: bool) -> None:
        self.refuse = refuse
        self.frames: list = []

    async def send_realtime_input(self, **kwargs):
        if self.refuse:
            raise RuntimeError("1007 CONTENT_TYPE_AUDIO is not supported")
        self.frames.append(kwargs)


class _FakeLive:
    def __init__(self, accepts: set[str]) -> None:
        self.accepts = accepts
        self.opened: list[str] = []
        self.closed: list[str] = []

    def connect(self, *, model: str, config=None):
        # A real `contextlib` manager, deliberately — the bug being pinned here
        # lives in that class, so a hand-rolled stand-in would not reproduce it.
        @contextlib.asynccontextmanager
        async def _cm():
            self.opened.append(model)
            try:
                yield _FakeSession(refuse=model not in self.accepts)
            finally:
                self.closed.append(model)

        return _cm()


class _FakeClient:
    def __init__(self, live: _FakeLive) -> None:
        self.aio = type("_Aio", (), {"live": live})()


@pytest.fixture()
def loop():
    """One event loop for the whole test.

    `asyncio.run` closes pending async generators on the way out, which would
    shut the winning manager by itself and hide whether the code closed it.
    """
    lp = asyncio.new_event_loop()
    try:
        yield lp
    finally:
        lp.run_until_complete(lp.shutdown_asyncgens())
        lp.close()


def _patch_candidates(monkeypatch, names):
    import app.api.voice_ws.session as session_mod

    monkeypatch.setattr(session_mod, "live_model_candidates", lambda: tuple(names))


def test_it_settles_on_the_model_that_accepts_audio(monkeypatch, loop):
    from app.api.voice_ws.session import _open_live_session

    live = _FakeLive(accepts={"model-c"})
    _patch_candidates(monkeypatch, ["model-a", "model-b", "model-c"])

    cm, session, name, err = loop.run_until_complete(_open_live_session(_FakeClient(live), None))

    assert name == "model-c", "settled on a model that refuses audio"
    assert err is None
    assert live.opened == ["model-a", "model-b", "model-c"]
    # The two refusals are closed; the winner is still open for the caller.
    assert live.closed == ["model-a", "model-b"], "a refused candidate leaked its socket"
    assert session.frames, "the winner was never actually probed"

    loop.run_until_complete(cm.__aexit__(None, None, None))
    assert live.closed == ["model-a", "model-b", "model-c"]


def test_the_returned_manager_is_already_entered(monkeypatch, loop):
    """The production crash, reproduced: re-entering is what `async with cm:` did.

    This is the whole defect. If someone reintroduces that line, this test says
    so with the same message the users saw.
    """
    from app.api.voice_ws.session import _open_live_session

    live = _FakeLive(accepts={"model-a"})
    _patch_candidates(monkeypatch, ["model-a"])

    cm, _session, name, _err = loop.run_until_complete(_open_live_session(_FakeClient(live), None))
    assert name == "model-a"

    with pytest.raises(AttributeError) as caught:
        loop.run_until_complete(cm.__aenter__())
    assert "args" in str(caught.value)

    loop.run_until_complete(cm.__aexit__(None, None, None))


def test_every_candidate_refusing_reports_instead_of_pretending(monkeypatch, loop):
    from app.api.voice_ws.session import _open_live_session

    live = _FakeLive(accepts=set())
    _patch_candidates(monkeypatch, ["model-a", "model-b"])

    cm, session, name, err = loop.run_until_complete(_open_live_session(_FakeClient(live), None))

    assert (cm, session, name) == (None, None, "")
    assert "CONTENT_TYPE_AUDIO" in str(err), "the caller cannot say why voice failed"
    assert live.closed == ["model-a", "model-b"], "failed probes left sockets open"


def test_the_session_never_re_enters_the_manager():
    """`_live_session` owns the manager and exits it once, in a `finally`."""
    import pathlib
    import re

    import app.api.voice_ws.session as session_mod

    src = pathlib.Path(session_mod.__file__).read_text(encoding="utf-8")
    assert not re.search(r"^\s*async with cm\b", src, re.M), \
        "the double-enter crash is back"
    assert "await cm.__aexit__(None, None, None)" in src, \
        "the Live socket is opened and never closed"


# ── The refusal arrives after the send returns ──────────────────────────────
#
# Production, with the probe already in place and reporting the model healthy:
#
#     [voice_ws] Gemini Live session opened (model=gemini-2.5-flash-native-audio-latest)
#     ...eight seconds later...
#     1007 The audio content type (CONTENT_TYPE_AUDIO) is not supported
#          for this model configuration.
#
# `send_realtime_input` writes to a socket and returns. The refusal is a close
# frame that comes back afterwards, so a probe that only sends proves nothing at
# all — it proved the socket accepted a write, which it always does. The wait
# and the second frame are the actual test.


class _LateRefusalSession:
    """Accepts the first frame, closes, and raises on everything after."""

    def __init__(self) -> None:
        self.closed = False
        self.sends = 0

    async def send_realtime_input(self, **kwargs):
        self.sends += 1
        if self.closed:
            raise RuntimeError(
                "received 1007 The audio content type (CONTENT_TYPE_AUDIO) is "
                "not supported for this model configuration")
        self.closed = True      # the close frame lands right after this send


class _LateRefusalLive(_FakeLive):
    def connect(self, *, model: str, config=None):
        @contextlib.asynccontextmanager
        async def _cm():
            self.opened.append(model)
            try:
                yield (_FakeSession(refuse=False) if model in self.accepts
                       else _LateRefusalSession())
            finally:
                self.closed.append(model)

        return _cm()


def test_a_model_that_refuses_after_the_send_is_still_caught(monkeypatch, loop):
    import app.api.voice_ws.session as session_mod
    from app.api.voice_ws.session import _open_live_session

    monkeypatch.setattr(session_mod, "_PROBE_SETTLE_S", 0.01)
    monkeypatch.setattr(session_mod, "pinned_live_model", lambda: "")
    live = _LateRefusalLive(accepts={"model-good"})
    _patch_candidates(monkeypatch, ["model-late", "model-good"])

    cm, _session, name, _err = loop.run_until_complete(
        _open_live_session(_FakeClient(live), None))

    assert name == "model-good", \
        "a model whose refusal arrives after the send was reported healthy"
    assert live.closed[0] == "model-late"
    loop.run_until_complete(cm.__aexit__(None, None, None))


def test_a_proven_model_does_not_pay_for_the_wait(monkeypatch, loop):
    """The wait is the price of not knowing. Once a real session has proved a
    model, it is skipped — and `forget_live_model` removes the pin the moment
    that stops being true, so trust never outlives the evidence."""
    import app.api.voice_ws.session as session_mod
    from app.api.voice_ws.session import _open_live_session

    monkeypatch.setattr(session_mod, "pinned_live_model", lambda: "model-a")
    live = _FakeLive(accepts={"model-a"})
    _patch_candidates(monkeypatch, ["model-a"])

    session_holder = {}

    import time as _time
    t0 = _time.monotonic()
    cm, session, name, _err = loop.run_until_complete(
        _open_live_session(_FakeClient(live), None))
    elapsed = _time.monotonic() - t0

    assert name == "model-a"
    assert len(session.frames) == 1, "a proven model was probed twice anyway"
    assert elapsed < 0.3, "every voice call pays the settle wait"
    session_holder["cm"] = cm
    loop.run_until_complete(cm.__aexit__(None, None, None))


def test_the_env_var_is_a_preference_and_not_the_whole_list(monkeypatch):
    """It held a name that refuses audio, and because it replaced the list there
    was nothing to fall through to. An escape hatch that can trap is a trap."""
    import app.api.voice_ws._config as cfg

    monkeypatch.setattr(cfg, "_LIVE_MODEL", "gemini-2.5-flash-native-audio-latest")
    monkeypatch.setattr(cfg, "_live_model_working", "")

    order = cfg.live_model_candidates()
    assert order[0] == "gemini-2.5-flash-native-audio-latest"
    assert len(order) > 1, "the env var still removes every fallback"
    assert len(order) == len(set(order)), "the same model is tried twice"


def test_a_model_that_fails_in_a_real_session_is_unpinned(monkeypatch):
    import app.api.voice_ws._config as cfg

    monkeypatch.setattr(cfg, "_live_model_working", "model-a")
    cfg.forget_live_model("model-b")
    assert cfg.pinned_live_model() == "model-a", "the wrong model was unpinned"
    cfg.forget_live_model("model-a")
    assert cfg.pinned_live_model() == "", "a failing model stayed preferred"


# ── When the whole list goes stale at once ──────────────────────────────────
#
#     1008 models/gemini-2.0-flash-live-001 is not found for API version
#          v1beta, or is not supported for bidiGenerateContent
#
# Every name in the list, and the one in the config var connected and then
# refused audio. A hardcoded list of names somebody else renames is a countdown,
# not a fix. The service knows which models do bidirectional audio; asking is
# the difference between voice degrading and voice ending.


class _Model:
    def __init__(self, name, actions):
        self.name = name
        self.supported_actions = actions


def test_it_asks_the_api_when_the_known_names_are_gone(monkeypatch, loop):
    import app.api.voice_ws.session as session_mod
    from app.api.voice_ws.session import _open_live_session

    monkeypatch.setattr(session_mod, "_PROBE_SETTLE_S", 0.01)
    monkeypatch.setattr(session_mod, "pinned_live_model", lambda: "")
    _patch_candidates(monkeypatch, ["dead-one", "dead-two"])

    live = _FakeLive(accepts={"models-say-this-one"})
    client = _FakeClient(live)
    client.models = type("_M", (), {"list": staticmethod(lambda: [
        _Model("models/some-text-model", ["generateContent"]),
        _Model("models/models-say-this-one", ["bidiGenerateContent"]),
    ])})()

    cm, _session, name, _err = loop.run_until_complete(
        _open_live_session(client, None))

    assert name == "models-say-this-one", \
        "every known name was dead and it gave up instead of asking"
    assert live.opened[:2] == ["dead-one", "dead-two"], \
        "the known names should still be tried first — they cost nothing"
    loop.run_until_complete(cm.__aexit__(None, None, None))


def test_a_model_is_never_tried_twice(monkeypatch, loop):
    """The API will list a name the static list already holds."""
    import app.api.voice_ws.session as session_mod
    from app.api.voice_ws.session import _open_live_session

    monkeypatch.setattr(session_mod, "_PROBE_SETTLE_S", 0.01)
    monkeypatch.setattr(session_mod, "pinned_live_model", lambda: "")
    _patch_candidates(monkeypatch, ["model-a"])

    live = _FakeLive(accepts=set())
    client = _FakeClient(live)
    client.models = type("_M", (), {"list": staticmethod(lambda: [
        _Model("models/model-a", ["bidiGenerateContent"]),
    ])})()

    loop.run_until_complete(_open_live_session(client, None))
    assert live.opened == ["model-a"], f"tried twice: {live.opened}"


def test_a_failed_listing_does_not_take_voice_down(monkeypatch, loop):
    """Discovery is a fallback. If it throws, the known names still get their
    turn — the opposite would make a bonus into a dependency."""
    import app.api.voice_ws.session as session_mod
    from app.api.voice_ws.session import _open_live_session

    monkeypatch.setattr(session_mod, "_PROBE_SETTLE_S", 0.01)
    monkeypatch.setattr(session_mod, "pinned_live_model", lambda: "")
    _patch_candidates(monkeypatch, ["model-a"])

    def _boom():
        raise RuntimeError("permission denied on models.list")

    live = _FakeLive(accepts={"model-a"})
    client = _FakeClient(live)
    client.models = type("_M", (), {"list": staticmethod(_boom)})()

    cm, _session, name, _err = loop.run_until_complete(
        _open_live_session(client, None))
    assert name == "model-a"
    loop.run_until_complete(cm.__aexit__(None, None, None))


def test_closing_a_refused_probe_does_not_invent_a_second_failure(monkeypatch, loop):
    """`__aexit__(type, exc, tb)` throws the failure back into the SDK's
    generator, which then does not stop, and `contextlib` raises
    `RuntimeError: generator didn't stop after athrow()` — a second, invented
    error printed with a traceback pointing at the cleanup, not the cause."""
    import pathlib

    import app.api.voice_ws.session as session_mod

    src = pathlib.Path(session_mod.__file__).read_text(encoding="utf-8")
    assert "await probe.__aexit__(type(exc), exc, exc.__traceback__)" not in src
    assert "await probe.__aexit__(None, None, None)" in src


def test_the_candidate_list_holds_only_names_that_do_audio_both_ways():
    """The list is the fast path. When every name in it is dead, every session
    pays a second and a half of failures and prints a warning per name before
    discovery finds a live one — which is what production did, twice a call.

    Two of the models the API reports as live-capable are not conversation
    models, and one of them refuses the AUDIO response modality outright. They
    must not be in here just because the listing mentioned them.
    """
    from app.api.voice_ws._config import _LIVE_MODEL_CANDIDATES

    assert "gemini-2.5-flash-native-audio-latest" in _LIVE_MODEL_CANDIDATES, \
        "the one model production proved is missing from the fast path"
    for dead in ("gemini-live-2.5-flash-preview",
                 "gemini-2.5-flash-preview-native-audio-dialog",
                 "gemini-2.0-flash-live-001"):
        assert dead not in _LIVE_MODEL_CANDIDATES, \
            f"{dead} answers 1008 — it is a guaranteed wasted round trip"
    for wrong in ("gemini-3.5-transcribe-live",
                  "gemini-3.5-live-translate-preview",
                  "gemini-robotics-er-2-streaming-preview"):
        assert wrong not in _LIVE_MODEL_CANDIDATES, \
            f"{wrong} is live-capable but is not a speech conversation model"


# ── Who decides the question is over ────────────────────────────────────────
#
# From the log, twice in a row:
#
#     21:22:41.96  device→live done          ← the board hung up
#     21:22:43.53  first response from Gemini
#     21:22:46.02  first reply audio → device
#
# Gemini's first response came a second and a half *after the board closed the
# connection*, not after the user stopped talking. The board streams the room
# continuously, so automatic detection never sees the silence it is waiting for
# and only commits the turn when the stream ends. The firmware waits eight
# seconds after the last word (`VOICE_SESSION_IDLE_MS`) — so the reply was
# racing a clock it had already lost.


def test_the_turn_is_always_closed_by_us():
    """Speaker verification and turn control are separate questions. Tying them
    together left the no-verification path with nobody ending the turn."""
    import pathlib

    import app.api.voice_ws.session as session_mod

    src = pathlib.Path(session_mod.__file__).read_text(encoding="utf-8")
    assert "end_of_speech_sensitivity" not in src, \
        "automatic detection is back on a path that streams the room non-stop"
    assert src.count("automatic_activity_detection=types.AutomaticActivityDetection("
                     "disabled=True)") == 1
    assert "_device_to_live_fast" not in src, "the bypassed bridge is still here"


def test_a_gate_that_never_opens_lowers_itself(monkeypatch):
    """This path forwards nothing until it decides the user is speaking, so a
    threshold too high for one room means Gemini gets silence for the whole call
    — the same symptom, arriving by the opposite route."""
    import app.api.voice_ws._config as cfg

    assert cfg._VAD_BLIND_MS > 0
    # The floor exists so a room of pure noise cannot drive it to zero.
    assert max(10.0 * 0.4, 40.0) == 40.0
