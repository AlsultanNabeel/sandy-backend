"""Ask Gemini a question the way the robot does, and say whether she answers.

**Why this exists.** Every fix to the voice path was costing the owner a deploy,
a phone call to his own robot, and a hunt through a log — one hypothesis per
round trip, at three in the morning. That is not a debugging loop, it is a
queue with a human in it.

Nothing about the question needs the robot. The only parts that matter are the
config we send, the system instruction we build, and the turn signals — and all
three run here. This opens a real Live session with the real config, sends real
speech, and reports the one fact that has been ambiguous for days: **did audio
come back.**

    python scripts/voice_probe.py                       # a tone, not speech
    python scripts/voice_probe.py question.wav          # mono 16-bit 16 kHz
    python scripts/voice_probe.py --say "شو مهامي اليوم؟"     # spoken by TTS
    python scripts/voice_probe.py --say "..." --think        # with thinking on

`--say` speaks the text with the same Gemini voice stack the product uses and
feeds the result in as if the owner had said it, which makes the probe a real
question and not a beep. `--think` leaves extended thinking enabled, so the two
runs can be compared — the reason it is off by default is six and a half
seconds of it against a robot that hangs up after eight.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import wave

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cloud"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

_FRAME_BYTES = 1280          # 40 ms at 16 kHz / 16-bit — what we send Gemini


def _speak(text: str) -> bytes:
    """Say the question out loud, in the product's own voice, at the board's rate.

    A tone proves the session opens; only speech proves she understood and
    answered. And the answer to "is thinking worth three seconds" cannot be
    argued — it has to be heard, twice, on the same sentence.
    """
    import audioop
    import io

    from app.integrations.gemini_tts import synthesize_voice_with_gemini

    wav = synthesize_voice_with_gemini(text, mood="neutral")
    if not wav:
        raise SystemExit("TTS returned nothing — check GEMINI_API_KEY")
    with wave.open(io.BytesIO(wav), "rb") as w:
        pcm = w.readframes(w.getnframes())
        rate = w.getframerate()
        if w.getnchannels() == 2:
            pcm = audioop.tomono(pcm, w.getsampwidth(), 1, 1)
    if rate != 16000:
        pcm, _ = audioop.ratecv(pcm, 2, 1, rate, 16000, None)
    return pcm


def _load(path: str | None) -> bytes:
    if not path:
        import math
        import struct

        # 2 s of a 220 Hz tone. Not speech, and not meant to be.
        out = bytearray()
        for i in range(16000 * 2):
            out += struct.pack("<h", int(8000 * math.sin(2 * math.pi * 220 * i / 16000)))
        return bytes(out)

    with wave.open(path, "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2 or w.getframerate() != 16000:
            raise SystemExit(
                f"{path}: need mono 16-bit 16 kHz, got {w.getnchannels()}ch "
                f"{w.getsampwidth() * 8}-bit {w.getframerate()}Hz")
        return w.readframes(w.getnframes())


async def main() -> int:
    from google import genai
    from google.genai import types

    from app.api.voice_ws._config import (
        _COMPRESS_TRIGGER_TOKENS,
        _COMPRESS_WINDOW_TOKENS,
        live_model_candidates,
    )

    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        raise SystemExit("GEMINI_API_KEY is not set")

    args = sys.argv[1:]
    think = "--think" in args
    args = [a for a in args if a != "--think"]
    if args and args[0] == "--say":
        audio = _speak(" ".join(args[1:]) or "مرحبا")
    else:
        audio = _load(args[0] if args else None)
    print(f"question: {len(audio) / 2 / 16000:.1f}s of audio")

    # The same instruction the robot gets, built the same way — this is the
    # thing most likely to be telling her to stay quiet, so it is not faked.
    try:
        from app.api.voice_ws.tools import _build_system_instruction

        instruction = _build_system_instruction(os.getenv("SANDY_PROBE_USER", ""))
        print(f"instruction: {len(instruction)} chars")
    except Exception as exc:  # noqa: BLE001 — the probe still has a job without it
        print(f"instruction unavailable ({exc}); using a bare one")
        instruction = "أنتِ ساندي. ردّي بصوتك على آخر شي قاله المستخدم."

    # **The tools go in, or the comparison is a lie.**
    #
    # Without them she reads the call out loud — `reminder_add(time=...)` — as
    # if it were a sentence, and that would be blamed on whatever else the run
    # was testing. The session the robot gets has them; so does this.
    try:
        from app.api.voice_ws.session import _build_live_tools

        live_tools = _build_live_tools(types)
        print(f"tools: {sum(len(t.function_declarations or []) for t in live_tools)}")
    except Exception as exc:  # noqa: BLE001
        print(f"tools unavailable ({exc})")
        live_tools = None

    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        tools=live_tools,
        system_instruction=types.Content(parts=[types.Part(text=instruction)],
                                         role="user"),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        thinking_config=None if think else types.ThinkingConfig(
            thinking_budget=0, include_thoughts=False),
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(
                disabled=True),
        ),
        context_window_compression=types.ContextWindowCompressionConfig(
            trigger_tokens=_COMPRESS_TRIGGER_TOKENS,
            sliding_window=types.SlidingWindow(
                target_tokens=_COMPRESS_WINDOW_TOKENS),
        ),
    )

    client = genai.Client(api_key=key)
    model = live_model_candidates()[0]
    print(f"model: {model}  thinking: {'on' if think else 'off'}")

    heard: list[str] = []
    said: list[str] = []
    audio_out = 0
    t0 = time.monotonic()
    first_audio_at = None

    async with client.aio.live.connect(model=model, config=config) as session:
        print(f"session open at {time.monotonic() - t0:.1f}s")

        await session.send_realtime_input(activity_start=types.ActivityStart())
        for i in range(0, len(audio), _FRAME_BYTES):
            await session.send_realtime_input(
                audio=types.Blob(data=audio[i:i + _FRAME_BYTES],
                                 mime_type="audio/pcm;rate=16000"))
        await session.send_realtime_input(activity_end=types.ActivityEnd())
        sent_at = time.monotonic()
        print(f"turn closed at {sent_at - t0:.1f}s")

        async def _read() -> None:
            nonlocal audio_out, first_audio_at
            async for response in session.receive():
                if response.tool_call:
                    names = [f.name for f in (response.tool_call.function_calls or [])]
                    said.append(f"[tool: {', '.join(names)}]")
                    return
                sc = response.server_content
                if not sc:
                    continue
                if sc.input_transcription and sc.input_transcription.text:
                    heard.append(sc.input_transcription.text)
                if sc.output_transcription and sc.output_transcription.text:
                    said.append(sc.output_transcription.text)
                if sc.model_turn:
                    for part in sc.model_turn.parts:
                        if part.inline_data and part.inline_data.data:
                            if first_audio_at is None:
                                first_audio_at = time.monotonic()
                            audio_out += len(part.inline_data.data)
                        if part.text:
                            said.append(part.text)
                if sc.turn_complete:
                    return

        try:
            await asyncio.wait_for(_read(), timeout=30)
        except asyncio.TimeoutError:
            print("no turn_complete within 30s")

    print()
    print(f"heard : {''.join(heard)!r}")
    print(f"said  : {''.join(said)!r}")
    print(f"audio : {audio_out} bytes ({audio_out / 2 / 24000:.1f}s)")
    if first_audio_at:
        print(f"first audio {first_audio_at - sent_at:.1f}s after the turn closed")

    if audio_out:
        print("\nVERDICT: she answered. Any silence in the room is below this "
              "point — the link to the robot, or the board's playback.")
        return 0
    print("\nVERDICT: no audio came back. The fault is here — the config, the "
          "instruction, or the turn signals.")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
