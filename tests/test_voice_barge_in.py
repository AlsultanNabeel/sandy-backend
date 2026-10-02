"""A reply is cut only by a voice: pitched sound counts, road and fan noise do not."""
from __future__ import annotations

import numpy as np

from app.api.voice_ws.session import _voiced

RATE = 16000
FRAME = 640  # 40 ms, what the board and the app send


def _frame(signal) -> np.ndarray:
    return np.clip(signal, -32767, 32767).astype("<i2")


def test_a_voice_pitch_counts():
    t = np.arange(FRAME) / RATE
    vowel = 6000 * np.sin(2 * np.pi * 160 * t) + 2500 * np.sin(2 * np.pi * 320 * t)
    assert _voiced(_frame(vowel))


def test_road_noise_and_engine_rumble_do_not():
    rng = np.random.default_rng(7)
    assert not _voiced(_frame(rng.normal(0, 8000, FRAME)))          # broadband road noise
    t = np.arange(FRAME) / RATE
    assert not _voiced(_frame(9000 * np.sin(2 * np.pi * 35 * t)))   # engine rumble, below a voice
    assert not _voiced(_frame(np.zeros(FRAME)))
