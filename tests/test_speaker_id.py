"""Unit tests for the pure helpers in features/speaker_id.py.

These don't need sherpa-onnx or the model — they cover PCM→float conversion,
cosine/normalize, the voiceprint encode/decode round-trip, and graceful
degradation when the engine isn't available.
"""
import importlib
from array import array

import numpy as np

import app.features.speaker_id as sid


def test_pcm_to_float_roundtrip():
    pcm = array("h", [0, 32767, -32768, 16384]).tobytes()
    out = sid._pcm_to_float(pcm)
    assert out.dtype == np.float32
    assert abs(out[0]) < 1e-6
    assert abs(out[1] - (32767 / 32768.0)) < 1e-4
    assert abs(out[2] - (-1.0)) < 1e-6


def test_pcm_to_float_drops_odd_trailing_byte():
    out = sid._pcm_to_float(array("h", [5, 6]).tobytes() + b"\x01")
    assert out.size == 2


def test_normalize_makes_unit_vector():
    v = sid._normalize(np.array([3.0, 4.0], dtype="float32"))
    assert abs(float(np.linalg.norm(v)) - 1.0) < 1e-6


def test_normalize_zero_vector_is_none():
    assert sid._normalize(np.zeros(4, dtype="float32")) is None


def test_cosine_identical_and_orthogonal():
    a = sid._normalize(np.array([1.0, 1.0], dtype="float32"))
    b = sid._normalize(np.array([1.0, 1.0], dtype="float32"))
    assert abs(sid._cosine(a, b) - 1.0) < 1e-6
    o1 = sid._normalize(np.array([1.0, 0.0], dtype="float32"))
    o2 = sid._normalize(np.array([0.0, 1.0], dtype="float32"))
    assert abs(sid._cosine(o1, o2)) < 1e-6


def test_a_voiceprint_is_never_stored_without_the_key(monkeypatch):
    """No key is a refusal, not a plaintext write.

    This used to assert the opposite — that `_encode_profile` falls back to
    base64 — and the fallback reads like graceful degradation right up until you
    say what it degrades to. base64 is a transport encoding. The row it wrote
    held the raw voiceprint, and a voiceprint is the one credential a person
    cannot rotate after a database is copied: it is their voice, for life. There
    is nothing to degrade to, so the write refuses and `enroll_speaker` says so
    instead of answering «تمام! صرت أعرف صوتك ✅» over a row that is not there.
    """
    monkeypatch.delenv("SANDY_BIO_KEY", raising=False)
    importlib.reload(sid)
    raw = np.array([0.1, -0.2, 0.3], dtype="float32").tobytes()
    assert sid._encode_profile(raw) is None

    # And the refusal reaches the user rather than being swallowed into a tick.
    monkeypatch.setattr(sid, "is_available", lambda: True)
    monkeypatch.setattr(sid, "_get_extractor", lambda: object())
    monkeypatch.setattr(sid, "_embed", lambda _b: sid._normalize(
        np.array([1.0, 0.0, 0.0], dtype="float32")))
    monkeypatch.setattr(sid, "get_db", lambda: {}, raising=False)
    ok, n, message = sid.enroll_speaker(7, [b"x" * 32])
    assert ok is False and n == 0 and message
    importlib.reload(sid)


def test_a_legacy_plaintext_voiceprint_is_still_readable(monkeypatch):
    """Rows enrolled before the refusal existed are plaintext base64, and
    locking those owners out of their own robot is not a security improvement —
    `get_profile_vector` re-encrypts them on the next read instead."""
    monkeypatch.delenv("SANDY_BIO_KEY", raising=False)
    importlib.reload(sid)
    import base64
    raw = np.array([0.1, -0.2, 0.3], dtype="float32").tobytes()
    legacy = base64.b64encode(raw).decode("ascii")
    assert sid._decode_profile(legacy) == raw


def test_profile_encode_decode_roundtrip_with_key(monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("SANDY_BIO_KEY", Fernet.generate_key().decode())
    importlib.reload(sid)
    raw = np.array([0.42, -0.99, 0.01], dtype="float32").tobytes()
    encoded = sid._encode_profile(raw)
    assert encoded.startswith("enc:")
    assert sid._decode_profile(encoded) == raw
    importlib.reload(sid)  # reset module crypto state for other tests


def test_graceful_when_engine_unavailable(monkeypatch):
    # Force the engine off (regardless of whether sherpa-onnx is installed in CI)
    # so enroll/verify degrade quietly — and so the test never hits the network
    # to download the model.
    monkeypatch.setattr(sid, "is_available", lambda: False)
    ok, n, msg = sid.enroll_speaker(123, [b"\x00\x01" * 10000])
    assert ok is False and n == 0 and isinstance(msg, str)
    match, score = sid.verify_speaker(123, b"\x00\x01" * 10000)
    assert match is False and score == 0.0


def test_a_voiceprint_that_cannot_be_read_keeps_the_gate_shut(monkeypatch):
    """SANDY_BIO_KEY missing or changed, or the read failing, is not «no voiceprint»:
    that answer turns the gate off and lets anyone by the robot act as its owner."""
    import mongomock
    from cryptography.fernet import Fernet
    from app import db as appdb
    from app.api.voice_ws import speaker

    d = mongomock.MongoClient().db
    appdb.configure(d)
    try:
        monkeypatch.setattr(sid, "_fernet_init", True)
        monkeypatch.setattr(sid, "_fernet", Fernet(Fernet.generate_key()))
        raw = np.array([0.6, 0.8], dtype="float32").tobytes()
        assert sid._save_profile("u1", raw, 5)
        monkeypatch.setattr(sid, "_fernet", Fernet(Fernet.generate_key()))

        assert sid.has_profile("u1"), "an unreadable voiceprint read as none"
        assert speaker._verify_owner(b"\x00\x01" * 16000, "u1") is False

        from pymongo.errors import PyMongoError

        def _down(*a, **k):
            raise PyMongoError("timed out")
        monkeypatch.setattr(d["sandy_voiceprints"].__class__, "find_one", _down)
        assert sid.has_profile("u1"), "a failed read turned the gate off"
        assert not sid.has_profile(""), "nobody has no voiceprint"
    finally:
        appdb.reset()


def test_a_failed_model_load_is_retried_not_kept_for_the_process(monkeypatch):
    """One failed download at boot used to leave the extractor empty until the next
    restart, and the owner was a stranger on every turn until then."""
    import sys
    import types

    built = []

    class _Extractor:
        dim = 192

        def __init__(self, config):
            built.append(config)

    fake = types.SimpleNamespace(SpeakerEmbeddingExtractorConfig=lambda **k: k,
                                 SpeakerEmbeddingExtractor=_Extractor)
    monkeypatch.setitem(sys.modules, "sherpa_onnx", fake)
    monkeypatch.setattr(sid, "_extractor", None)
    monkeypatch.setattr(sid, "_extractor_retry_at", 0.0)
    monkeypatch.setattr(sid, "_extractor_backoff_s", sid._EXTRACTOR_RETRY_MIN_S)
    answers = iter([None, "/tmp/model.onnx"])
    monkeypatch.setattr(sid, "_ensure_model", lambda: next(answers))

    assert sid._get_extractor() is None
    assert sid._get_extractor() is None, "retried at once instead of backing off"
    monkeypatch.setattr(sid, "_extractor_retry_at", 0.0)   # the wait is over
    assert isinstance(sid._get_extractor(), _Extractor)
    assert sid.can_verify()


def test_without_the_model_she_cannot_tell_rather_than_calls_the_owner_a_stranger(monkeypatch):
    import mongomock
    from cryptography.fernet import Fernet
    from app import db as appdb
    from app.api.voice_ws import speaker

    d = mongomock.MongoClient().db
    appdb.configure(d)
    try:
        monkeypatch.setattr(sid, "_fernet_init", True)
        monkeypatch.setattr(sid, "_fernet", Fernet(Fernet.generate_key()))
        assert sid._save_profile("u1", np.array([0.6, 0.8], dtype="float32").tobytes(), 5)
        monkeypatch.setattr(sid, "can_verify", lambda: False)
        assert speaker._verify_owner(b"\x00\x01" * 16000, "u1") is None
        note = speaker._speaker_directive(None)
        assert "شخص آخر" not in note, "a model that did not load called the owner a stranger"
        assert "ما قدرتي تتأكدي" in note
    finally:
        appdb.reset()
