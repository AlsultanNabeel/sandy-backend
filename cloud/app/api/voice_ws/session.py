"""voice_ws session."""
from __future__ import annotations
import logging

import asyncio
import hashlib
import hmac as _hmac
import json
import os
import time
from typing import Any, Dict, List
from app.api.voice_ws._config import (
    logger,
    _HMAC_KEY,
    _LEGACY_SECRET,
    _LIVE_MODEL,
    _ANTI_REPLAY_MS,
    _SENSITIVE_TOOLS,
    _VAD_RMS_THRESHOLD,
    _VAD_SILENCE_MS,
    _VAD_MIN_UTTER_MS,
)
from app.api.voice_ws.speaker import (
    _RecentAudio,
    _speaker_gate_enabled,
    _verify_and_inject,
    _verify_owner,
)
from app.api.voice_ws.memory import (
    _save_voice_turn,
    _stm_chat_id,
)
from app.api.voice_ws.tools import (
    _build_live_tools,
    _build_system_instruction,
    _dispatch_tool,
    _make_dispatcher,
)


def register_voice_ws(app) -> None:
    """Attach the /voice WebSocket route to an existing Flask app."""
    try:
        from flask_sock import Sock
    except ImportError:
        logger.warning("[voice_ws] flask-sock not installed — /voice disabled")
        return

    sock = Sock(app)

    @sock.route("/voice")
    def voice_stream(ws):
        remote = getattr(ws, "environ", {}).get("REMOTE_ADDR", "?")
        logger.info("[voice_ws] device connected from %s", remote)
        try:
            if not _authenticate(ws, remote):
                return
            asyncio.run(_live_session(ws, remote))
        except Exception as exc:
            logger.warning("[voice_ws] session error (%s): %s", remote, exc)
        finally:
            logger.info("[voice_ws] device disconnected from %s", remote)

    @sock.route("/voice/enroll")
    def voice_enroll(ws):
        """تسجيل بصمة المالك من نفس مايك الاختبار (يحلّ اختلاف القناة عن تيليجرام)."""
        remote = getattr(ws, "environ", {}).get("REMOTE_ADDR", "?")
        logger.info("[voice_ws] enroll connected from %s", remote)
        try:
            if not _authenticate(ws, remote):
                return
            _enroll_session(ws, remote)
        except Exception as exc:
            logger.warning("[voice_ws] enroll error (%s): %s", remote, exc)
        finally:
            logger.info("[voice_ws] enroll disconnected from %s", remote)


def _enroll_session(ws, remote: str) -> None:
    """يجمع مقاطع PCM من العميل ويبني بصمة المالك.

    البروتوكول (بعد المصافحة):
      • frames ثنائية = PCM 16-bit/16kHz mono (المقطع الحالي).
      • {"type":"utterance_end"} = أنهِ المقطع الحالي وضِفه للقائمة.
      • {"type":"enroll_done"}   = ابنِ البصمة واحفظها وأرسل النتيجة.
      • {"type":"enroll_cancel"} = ألغِ بدون حفظ.
    """
    from app.features import speaker_id

    chat_id = _stm_chat_id()
    if not chat_id:
        _send_json(ws, {"type": "error", "msg": "no_owner"})
        return

    samples: List[bytes] = []
    cur = bytearray()
    while True:
        try:
            frame = ws.receive(timeout=120)
        except Exception:
            break
        if frame is None:
            break
        if isinstance(frame, (bytes, bytearray)):
            cur.extend(frame)
            continue
        try:
            msg = json.loads(frame)
        except Exception:  # noqa: BLE001
            continue
        kind = msg.get("type")
        if kind == "utterance_end":
            if cur:
                samples.append(bytes(cur))
                cur = bytearray()
            _send_json(ws, {"type": "enrolled", "n": len(samples)})
        elif kind == "enroll_cancel":
            _send_json(ws, {"type": "enroll_result", "ok": False, "msg": "أُلغي التسجيل."})
            return
        elif kind == "enroll_done":
            if cur:  # آخر مقطع بدون utterance_end صريح
                samples.append(bytes(cur))
                cur = bytearray()
            ok, n, text = speaker_id.enroll_speaker(chat_id, samples)
            logger.info("[voice_ws] enroll result ok=%s n=%d (%s)", ok, n, remote)
            _send_json(ws, {"type": "enroll_result", "ok": ok, "n": n, "msg": text})
            return


# Auth

def _authenticate(ws, remote: str) -> bool:
    try:
        raw = ws.receive(timeout=5)
    except Exception:
        logger.warning("[voice_ws] handshake timeout from %s", remote)
        return False

    if raw is None:
        return False

    # Legacy plain-text secret (dev / echo tests). Constant-time compare.
    if _LEGACY_SECRET and isinstance(raw, str) and _hmac.compare_digest(raw, _LEGACY_SECRET):
        ws.send("AUTH_OK")
        return True

    # Web (browser) handshake via JWT: {"type":"hello","token":"<jwt>"}.
    # Live voice is the owner experience (full persona and shared memory), so
    # we only accept an owner token here and turn guests away.
    if isinstance(raw, str) and raw.lstrip().startswith("{"):
        try:
            _m = json.loads(raw)
        except Exception:  # noqa: BLE001
            _m = None
        if isinstance(_m, dict) and _m.get("type") == "hello" and _m.get("token"):
            from app.api.auth_handlers import verify_token
            claims = verify_token(str(_m.get("token")))
            if claims and claims.get("role") == "owner":
                ws.send(json.dumps({"type": "auth_ok"}))
                logger.info("[voice_ws] web auth OK (owner) remote=%s", remote)
                return True
            ws.send(json.dumps({"type": "error", "msg": "owner_only"}))
            return False

    # HMAC handshake
    if _HMAC_KEY and isinstance(raw, str):
        try:
            msg = json.loads(raw)
            if msg.get("type") != "hello":
                raise ValueError("not hello")
            device_id = str(msg["device_id"])
            ts = int(msg["ts"])
            token = str(msg["hmac"])

            now_ms = int(time.time() * 1000)
            if abs(now_ms - ts) > _ANTI_REPLAY_MS:
                logger.warning("[voice_ws] replay rejected from %s (delta=%d ms)", remote, abs(now_ms - ts))
                ws.send(json.dumps({"type": "error", "msg": "replay"}))
                return False

            expected = _hmac.new(
                _HMAC_KEY,
                f"{device_id}{ts}".encode(),
                hashlib.sha256,
            ).hexdigest()
            if not _hmac.compare_digest(expected, token):
                logger.warning("[voice_ws] HMAC invalid from %s", remote)
                ws.send(json.dumps({"type": "error", "msg": "auth_fail"}))
                return False

            ws.send(json.dumps({"type": "auth_ok"}))
            logger.info("[voice_ws] auth OK device=%s remote=%s", device_id, remote)
            return True
        except Exception as exc:
            logger.warning("[voice_ws] handshake error from %s: %s", remote, exc)
            ws.send(json.dumps({"type": "error", "msg": "bad_handshake"}))
            return False

    # No auth configured. Stay closed unless an explicit dev flag opts in,
    # so a missing env var in prod can't leave the socket wide open.
    if not _HMAC_KEY and not _LEGACY_SECRET:
        if os.environ.get("SANDY_WS_ALLOW_OPEN") == "1":
            logger.warning("[voice_ws] no auth configured, open access (dev) from %s", remote)
            return True
        logger.error("[voice_ws] no auth configured and SANDY_WS_ALLOW_OPEN != 1, refusing %s", remote)
        ws.send(json.dumps({"type": "error", "msg": "auth_not_configured"}))
        return False

    ws.send(json.dumps({"type": "error", "msg": "auth_fail"}))
    return False


# Gemini Live session

async def _live_session(ws, remote: str) -> None:
    """Open a Gemini Live speech-to-speech session and bridge it to the device WS."""
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        logger.error("[voice_ws] google-genai not installed")
        _send_json(ws, {"type": "error", "msg": "server_error"})
        return

    from app.config import GEMINI_API_KEY, GEMINI_TTS_VOICE

    if not GEMINI_API_KEY:
        logger.error("[voice_ws] GEMINI_API_KEY not set")
        _send_json(ws, {"type": "error", "msg": "server_error"})
        return

    system_instruction = await asyncio.get_event_loop().run_in_executor(
        None, _build_system_instruction
    )
    live_tools = _build_live_tools(types)

    gate_on = _speaker_gate_enabled()
    voice_name = (GEMINI_TTS_VOICE or "Aoede").strip()
    config_kwargs: Dict[str, Any] = dict(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
            )
        ),
        system_instruction=types.Content(
            parts=[types.Part(text=system_instruction)],
            role="user",
        ),
        tools=live_tools or [],
        # بدون هدول، التفريغ النصي ما بيوصل أبداً → _save_voice_turn ما بينحفظ
        # → محادثات الصوت ما بتظهر بذاكرة التلي/الويب (الذاكرة الموحدة).
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )
    if gate_on:
        # التحقّق مفعّل → نطفّي الكشف التلقائي ونتحكّم بنهاية الدور يدوياً عشان
        # نتحقّق من الصوت ونحقن الهوية قبل ما يردّ الموديل.
        config_kwargs["realtime_input_config"] = types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(disabled=True),
        )
    else:
        # التحقّق مطفّى → نسيب Gemini يكشف الدور، بس نضبطه يردّ بسرعة لحظة ما
        # تسكت (صمت نهاية أقصر + حساسية نهاية عالية) عشان الرد يكون فوري.
        config_kwargs["realtime_input_config"] = types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(
                end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH,
                # كل ما قلّت، أسرع ما تردّ بعد ما يسكت — بس لو نزلت كتير بتقاطعه
                # وهو واقف بنص جملة. ٣٥٠ توازن: ردّ أسرع بدون قطع. عيّرها لو لزم.
                silence_duration_ms=350,
                prefix_padding_ms=200,
            ),
        )
    config = types.LiveConnectConfig(**config_kwargs)

    client = genai.Client(api_key=GEMINI_API_KEY)
    dispatcher = _make_dispatcher()

    try:
        async with client.aio.live.connect(model=_LIVE_MODEL, config=config) as session:
            logger.info(
                "[voice_ws] Gemini Live session opened for %s (gate=%s)", remote, gate_on
            )

            recent = _RecentAudio()
            if gate_on:
                t_in = asyncio.create_task(_device_to_live(ws, session, recent))
            else:
                t_in = asyncio.create_task(_device_to_live_fast(ws, session))
            t_out = asyncio.create_task(_live_to_device(ws, session, dispatcher, recent))

            done, pending = await asyncio.wait(
                [t_in, t_out],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    logging.getLogger(__name__).debug("ignoring non-critical error", exc_info=True)
            # Retrieve exceptions from the finished side too, or asyncio logs a
            # noisy "Task exception was never retrieved" after every disconnect.
            for t in done:
                if not t.cancelled() and t.exception():
                    logger.info("[voice_ws] bridge task ended: %s", t.exception())

    except Exception as exc:
        logger.error("[voice_ws] Live session error (%s): %s", remote, exc)
        _send_json(ws, {"type": "error", "msg": "live_error"})


async def _device_to_live_fast(ws, session) -> None:
    """تمرير مباشر للصوت — Gemini يكشف الدور تلقائياً (أسرع، يُستعمل لما التحقّق مطفّى).

    بلا VAD عندنا، بلا إشارات يدوية، بلا تحقّق — أقل تأخير ممكن للرد.
    """
    from google.genai import types

    loop = asyncio.get_event_loop()
    while True:
        try:
            chunk = await loop.run_in_executor(None, ws.receive)
        except Exception:  # device closed mid-session (ConnectionClosed)
            break
        if chunk is None:
            break
        if not isinstance(chunk, (bytes, bytearray)):
            continue
        await session.send_realtime_input(
            audio=types.Blob(data=bytes(chunk), mime_type="audio/pcm;rate=16000")
        )


async def _device_to_live(ws, session, recent: "_RecentAudio") -> None:
    """Read PCM frames from the device and stream to Live with manual turn control.

    We run our own VAD: on speech we open an activity, and on about 700ms of
    silence we close it. Before closing we first verify who spoke and inject
    their persona, so Sandy replies with the right personality from the very
    first sentence (owner vs guest).
    """
    from google.genai import types
    import numpy as np

    loop = asyncio.get_event_loop()
    speaking = False
    silence_ms = 0.0
    utter_ms = 0.0

    async def _send_audio(chunk: bytes) -> None:
        await session.send_realtime_input(
            audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000")
        )

    while True:
        try:
            chunk = await loop.run_in_executor(None, ws.receive)
        except Exception:  # device closed mid-session (ConnectionClosed)
            break
        if chunk is None:
            break
        if not isinstance(chunk, (bytes, bytearray)):
            continue
        chunk = bytes(chunk)
        samples = np.frombuffer(chunk, dtype="<i2")
        if samples.size == 0:
            continue
        rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))
        ms = samples.size / 16000 * 1000
        is_speech = rms >= _VAD_RMS_THRESHOLD

        if is_speech and not speaking:
            # Speech onset, open a manual activity. We do NOT clear `recent`
            # here: verification needs a few seconds of audio for a reliable
            # CAM++ embedding, so we keep a rolling window (last ~5s of speech,
            # which is dominated by this speaker).
            speaking = True
            silence_ms = 0.0
            utter_ms = 0.0
            await session.send_realtime_input(activity_start=types.ActivityStart())

        if speaking:
            recent.add(chunk)
            await _send_audio(chunk)
            utter_ms += ms
            silence_ms = 0.0 if is_speech else silence_ms + ms
            if silence_ms >= _VAD_SILENCE_MS:
                # End of utterance: verify the speaker and inject persona before the reply.
                if utter_ms >= _VAD_MIN_UTTER_MS:
                    await _verify_and_inject(session, recent.snapshot())
                await session.send_realtime_input(activity_end=types.ActivityEnd())
                speaking = False
                silence_ms = 0.0
                utter_ms = 0.0
        # Idle silence before any speech: don't forward it, saves bandwidth.


async def _live_to_device(ws, session, dispatcher, recent: "_RecentAudio") -> None:
    """Read Gemini Live responses, relay audio to the device, handle tool calls."""
    from google.genai import types

    from app.agent.guards import DESTRUCTIVE_TOOLS

    loop = asyncio.get_event_loop()
    gate_on = _speaker_gate_enabled()
    _user_buf: List[str] = []
    _sandy_buf: List[str] = []
    # Destructive tools already prompted for spoken confirmation this session;
    # the model's re-call after the user confirms is allowed through.
    awaited_confirm: set = set()

    async def _handle(response) -> bool:
        """Process one Live response; return True to stop the session.

        Speaker identification + persona injection happen in _device_to_live at
        end-of-utterance (manual turn control), so this side just relays audio,
        saves STM, and gates sensitive tools.
        """

        # Capture user speech transcript
        if response.server_content and response.server_content.input_transcription:
            t = response.server_content.input_transcription.text
            if t:
                _user_buf.append(t)

        # Capture Sandy's speech transcript (native-audio models don't put
        # text in model_turn parts, so this is the only reliable source).
        if response.server_content and response.server_content.output_transcription:
            t = response.server_content.output_transcription.text
            if t:
                _sandy_buf.append(t)

        # Barge-in: Gemini noticed the user talking over Sandy and stopped
        # generating — tell the device to dump its buffered audio so she
        # actually goes quiet instead of finishing the stale reply.
        if response.server_content and response.server_content.interrupted:
            await loop.run_in_executor(None, _send_json, ws, {"type": "interrupted"})

        # Audio plus text response: relay the audio, capture the text.
        if response.server_content and response.server_content.model_turn:
            for part in response.server_content.model_turn.parts:
                if part.inline_data and part.inline_data.data:
                    await loop.run_in_executor(None, ws.send, part.inline_data.data)
                if part.text:
                    _sandy_buf.append(part.text)

        # Turn complete: persist the turn for cross-platform memory only.
        if response.server_content and response.server_content.turn_complete:
            await loop.run_in_executor(None, _send_json, ws, {"type": "end_turn"})
            user_text = " ".join(_user_buf).strip()
            sandy_text = " ".join(_sandy_buf).strip()

            # Save the turn so Telegram/web/voice keep sharing one memory. We
            # deliberately do NOT re-inject conversation history back into the
            # live session: Gemini's native-audio model treats an injected text
            # turn as live input and does not reliably honor a "don't reply" tag
            # (confirmed upstream), so replaying past turns made her answer the
            # OLD topic — "turn off the light" → "I added the eggs". The live
            # session keeps its own in-session context; long-term memory is
            # seeded once in the system instruction at session start.
            # Proof line for the "she didn't reply" case: did Gemini transcribe
            # the user, and did it produce any reply? heard=non-empty + replied=0
            # means she heard but stayed silent (turn/VAD issue); heard empty
            # means the audio never made it (mic/device side — check serial).
            logger.info("[voice_ws] turn done: heard=%r replied=%d chars",
                        user_text[:120], len(sandy_text))
            if user_text and sandy_text:
                await loop.run_in_executor(None, _save_voice_turn, user_text, sandy_text)

            _user_buf.clear()
            _sandy_buf.clear()

        # Tool calls: dispatch them and return the result to Live.
        if response.tool_call and dispatcher:
            fn_responses: List[types.FunctionResponse] = []
            for fc in response.tool_call.function_calls:
                # V4.4–V4.5: أمر حسّاس + البوابة مفعّلة → تأكّد إنه صوت المالك أولاً.
                if gate_on and fc.name in _SENSITIVE_TOOLS:
                    verified = await loop.run_in_executor(
                        None, _verify_owner, recent.snapshot()
                    )
                    if not verified:
                        fn_responses.append(types.FunctionResponse(
                            id=fc.id, name=fc.name,
                            response={"output": (
                                "ما قدرت أتأكد إنه صوتك. لا تنفّذي الأمر — "
                                "اسألي بلطف: مين معي؟"
                            )},
                        ))
                        continue
                # Destructive op → require a spoken confirmation first, regardless
                # of the speaker gate (mirrors the Track 1.2 text guard). The model
                # asks for confirmation and only re-calls the tool once the user
                # confirms; that second call is let through. If the speaker gate
                # already refused above we've continued, so no double-prompt.
                if fc.name in DESTRUCTIVE_TOOLS and fc.name not in awaited_confirm:
                    awaited_confirm.add(fc.name)
                    fn_responses.append(types.FunctionResponse(
                        id=fc.id, name=fc.name,
                        response={"output": (
                            "عملية تحتاج تأكيد صوتي. لا تنفّذيها الآن — "
                            "اسألي المستخدم تأكيد صريح بصوته، ونفّذي فقط إذا أكّد."
                        )},
                    ))
                    continue
                awaited_confirm.discard(fc.name)
                result = await loop.run_in_executor(
                    None, _dispatch_tool, dispatcher, fc.name, dict(fc.args or {})
                )
                fn_responses.append(
                    types.FunctionResponse(
                        id=fc.id,
                        name=fc.name,
                        response={"output": result.get("reply", "")},
                    )
                )
            await session.send_tool_response(function_responses=fn_responses)

        # Server is going away: stop relaying.
        if response.go_away:
            logger.info("[voice_ws] Live go_away received, closing session")
            return True
        return False

    # session.receive() yields one turn then ends, so we loop to keep the
    # conversation going across turns (the session itself stays open). We exit
    # on go_away, an error, or the device closing.
    while True:
        try:
            stop = False
            async for response in session.receive():
                if await _handle(response):
                    stop = True
                    break
            if stop:
                break
        except Exception as exc:
            logger.info("[voice_ws] Live receive loop ended: %s", exc)
            break


# Helpers

def _send_json(ws, payload: Dict[str, Any]) -> None:
    try:
        ws.send(json.dumps(payload, ensure_ascii=False))
    except Exception:
        logging.getLogger(__name__).debug("ignoring non-critical error", exc_info=True)
