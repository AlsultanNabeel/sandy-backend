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
