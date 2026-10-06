"""The read-aloud WAV is labelled with the rate Gemini's audio was made at (it says so
in the part's mime type, 24 kHz); labelled 22.05 kHz it played slow and low."""
import io
import types
import wave

import pytest


def _response(mime, pcm):
    part = types.SimpleNamespace(inline_data=types.SimpleNamespace(mime_type=mime, data=pcm))
    cand = types.SimpleNamespace(content=types.SimpleNamespace(parts=[part]))
    return types.SimpleNamespace(candidates=[cand])


@pytest.mark.parametrize("mime, rate", [("audio/L16;codec=pcm;rate=24000", 24000),
                                        ("audio/L16;rate=16000", 16000),
                                        ("audio/L16", 24000)])
def test_the_wav_carries_the_rate_the_audio_was_made_at(monkeypatch, mime, rate):
    pytest.importorskip("google.genai")
    from app.integrations import gemini_tts

    class _Models:
        def generate_content(self, **kw):
            return _response(mime, b"\x00\x00" * 2400)

    monkeypatch.setattr(gemini_tts, "_get_genai_client",
                        lambda key: types.SimpleNamespace(models=_Models()))
    wav = gemini_tts._do_synthesize("أهلين", "neutral", "k")
    with wave.open(io.BytesIO(wav)) as w:
        assert w.getframerate() == rate
