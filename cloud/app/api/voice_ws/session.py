"""voice_ws session."""
from __future__ import annotations
import logging

import asyncio
import hashlib
import hmac as _hmac
import json
import os
import re
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional
from app.api.voice_ws._config import (
    logger,
    _HMAC_KEY,
    _LEGACY_SECRET,
    forget_live_model,
    live_model_candidates,
    pinned_live_model,
    remember_live_model,
    _ANTI_REPLAY_MS,
    _APP_DUPLEX,
    _APP_PREFIX_MS,
    _APP_SILENCE_MS,
    _APP_TURNS_BY_GEMINI,
    _VAD_SILENCE_MS,
    _BACKLOG_FRAMES,
    _BARGE_MIN_MS,
    _VOICED_MIN,
    _CONTINUE_MIN_MS,
    _ONSET_VOICED_MS,
    _CHUNK_BYTES,
    _HELD_MS_MAX,
    _SILENCE_GAP_S,
    _COMPRESS_TRIGGER_TOKENS,
    _COMPRESS_WINDOW_TOKENS,
    _VAD_FLOOR_FACTOR,
    _VAD_FLOOR_MIN_FRAMES,
    _VAD_FLOOR_MS,
    _VAD_MAX_UTTER_MS,
    _VAD_ROOM_MAX,
    _VAD_ROOM_MS,
    _VAD_RMS_FLOOR,
    _VAD_STUCK_MS,
    _VAD_MIN_UTTER_MS,
)
from app.api.voice_ws import face
from app.api.voice_ws.speaker import (
    _RecentAudio,
    _is_sensitive_call,
    _speaker_gate_enabled,
    _learn_voice,
    _verify_and_inject,
    _verify_owner,
)
from app.api.voice_ws.memory import (
    session_context,
    _save_voice_turn,
    _stm_chat_id,
    get_voice_channel,
    get_voice_identity,
    load_recent_turns,
    resolve_speaker_label,
    set_voice_speaker_label,
    set_voice_channel,
    set_voice_identity,
)
from app.api.voice_ws.tools import (
    _build_cached_instruction,
    _build_live_tools,
    _dispatch_tool,
    with_recent_turns,
)


# How long a reply may keep streaming after the robot stops sending audio.
_REPLY_DRAIN_S = 20

# Enough for a generous enrolment (16 kHz · 16-bit · mono = 32 KB/s → ~2 min).
_ENROLL_MAX_BYTES = 4 * 1024 * 1024


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
    total = 0
    while True:
        try:
            frame = ws.receive(timeout=120)
        except Exception:
            break
        if frame is None:
            break
        if isinstance(frame, (bytes, bytearray)):
            # Bounded, or a client that kept streaming held a thread and grew this forever.
            total += len(frame)
            if total > _ENROLL_MAX_BYTES:
                _send_json(ws, {"type": "enroll_result", "ok": False, "msg": "too_long"})
                return
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
    # This server thread served other connections before: whoever it spoke for
    # then must not carry over to a board nobody has paired yet.
    set_voice_identity("")
    set_voice_channel("")
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

    # Browser/app handshake via JWT: {"type":"hello","token":"<jwt>"}; guests are refused.
    if isinstance(raw, str) and raw.lstrip().startswith("{"):
        try:
            _m = json.loads(raw)
        except Exception:  # noqa: BLE001
            _m = None
        if isinstance(_m, dict) and _m.get("type") == "hello" and _m.get("token"):
            from app.api.auth_handlers import verify_token
            claims = verify_token(str(_m.get("token")))
            # أي حساب مسجّل (مش «المالك» بس)؛ الهوية بتقيّد كل قراءة وكتابة بالجلسة.
            if claims and claims.get("role") in ("owner", "user"):
                uid = str(claims.get("user_id") or "")
                if not uid:
                    ws.send(json.dumps({"type": "error", "msg": "auth_fail"}))
                    return False
                set_voice_identity(uid)
                set_voice_channel(_APP_CHANNEL)
                # `duplex`: افتح المايك وهي بتحكي؛ القرار بالسيرفر عشان التراجع يكون بلا بناء.
                ws.send(json.dumps({"type": "auth_ok",
                                    "duplex": _APP_DUPLEX}))
                logger.info("[voice_ws] app voice OK user=%s remote=%s", uid, remote)
                return True
            ws.send(json.dumps({"type": "error", "msg": "auth_fail"}))
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
            kv = int(msg.get("kv") or 1)

            now_ms = int(time.time() * 1000)
            if abs(now_ms - ts) > _ANTI_REPLAY_MS:
                logger.warning("[voice_ws] replay rejected from %s (delta=%d ms)", remote, abs(now_ms - ts))
                ws.send(json.dumps({"type": "error", "msg": "replay"}))
                return False

            # A board with its own key says so (`kv` 2) and is checked against it
            # alone; the shared key is refused once its own key is confirmed.
            from app.features.device_keys import (
                KEY_VERSION, KeyUnreadable, confirm_key, get_key, issue_key,
            )
            try:
                record = get_key(device_id)
            except KeyUnreadable:
                # Our fault (the storage key), not the board's: no lockout, key kept.
                logger.error("[voice_ws] key record of %s cannot be read — check "
                             "SANDY_LTM_KEY", device_id)
                ws.send(json.dumps({"type": "error", "msg": "server_error"}))
                return False
            if kv == KEY_VERSION:
                if not record:
                    # Revoked or never issued: the board re-enrols with the shared key.
                    logger.warning("[voice_ws] %s signed with a key we do not hold",
                                   device_id)
                    ws.send(json.dumps({"type": "error", "msg": "key_unknown"}))
                    return False
                sign_key = record["key"]
            else:
                if record and record["state"] == "confirmed":
                    logger.warning("[voice_ws] shared key refused for %s — it has "
                                   "its own key (remote=%s)", device_id, remote)
                    ws.send(json.dumps({"type": "error", "msg": "auth_fail"}))
                    return False
                sign_key = _HMAC_KEY

            expected = _hmac.new(
                sign_key,
                f"{device_id}{ts}".encode(),
                hashlib.sha256,
            ).hexdigest()
            if not _hmac.compare_digest(expected, token):
                logger.warning("[voice_ws] HMAC invalid from %s", remote)
                ws.send(json.dumps({"type": "error", "msg": "auth_fail"}))
                return False
            if kv == KEY_VERSION and record["state"] == "issued":
                confirm_key(device_id)

            # الروبوت بيحكي باسم صاحبه المسجّل بالوحدة؛ لوح غير مربوط بيحكي بلا ذاكرة شخص.
            from app.features.node_store import get_node_any_tenant
            node = get_node_any_tenant(device_id) or {}
            owner = str(node.get("user_id") or "")
            if owner:
                set_voice_identity(owner)
            else:
                logger.warning("[voice_ws] device %s is not paired to anyone", device_id)
            set_voice_channel(_ROBOT_CHANNEL)

            # هون بيتسلّم اللوح بيانات الوسيط الخاصة فيه: المصافحة موثّقة بمفتاح غير
            # مفتاح الوسيط المشترك. بلا سطر بالجدول بيضلّ ع بياناته الحالية.
            reply: Dict[str, Any] = {"type": "auth_ok"}
            try:
                from app.features.broker_creds import creds_for_device
                creds = creds_for_device(device_id)
                if creds:
                    reply["broker"] = creds
            except (ImportError, ValueError, TypeError, AttributeError) as exc:
                # إضافة ع المصافحة، مش شرط فيها.
                logger.warning("[voice_ws] broker credential lookup failed for %s: %s",
                               device_id, exc)

            # A paired board still on the shared key gets its own key in this reply.
            if kv != KEY_VERSION and owner:
                try:
                    own = issue_key(device_id)
                    if own:
                        reply["device_key"] = own
                except Exception as exc:  # noqa: BLE001 — enrolment is extra, not a gate
                    logger.warning("[voice_ws] device key issue failed for %s: %s",
                                   device_id, exc)

            ws.send(json.dumps(reply))
            logger.info("[voice_ws] auth OK device=%s owner=%s remote=%s creds=%s key=%s",
                        device_id, owner or "—", remote,
                        "sent" if "broker" in reply else "—",
                        "own" if kv == KEY_VERSION else
                        ("issued" if "device_key" in reply else "shared"))
            return True
        except (KeyError, TypeError, ValueError) as exc:
            # The hello itself is malformed: the board's doing, and it backs off.
            logger.warning("[voice_ws] handshake error from %s: %s", remote, exc)
            ws.send(json.dumps({"type": "error", "msg": "bad_handshake"}))
            return False
        except Exception as exc:  # noqa: BLE001 — anything else is ours (a database read)
            logger.error("[voice_ws] handshake failed on our side for %s: %s", remote, exc)
            ws.send(json.dumps({"type": "error", "msg": "server_error"}))
            return False

    # No auth configured: stay closed unless an explicit dev flag opts in.
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

class _DeviceReader:
    """Drain the device socket from the moment the session starts.

    Opening Live takes seconds; unread frames would block the robot's writes and it
    would hang up. The buffer is bounded and drops the oldest frame when full.
    """

    _FRAME_MS = 20  # the robot sends ~20ms of PCM per frame

    # Each blocking read waits at most this long, so a stopped reader exits
    # promptly: a parked executor thread stalls asyncio.run() shutdown and holds
    # one of gunicorn's 16 threads.
    _POLL_S = 0.25

    # Returned on close, so a real close isn't confused with a quiet poll.
    _CLOSED = object()

    def __init__(self, ws, buffer_ms: int = 8000):
        self._ws = ws
        self._q: asyncio.Queue = asyncio.Queue(maxsize=buffer_ms // self._FRAME_MS)
        self._task: Optional[asyncio.Task] = None
        self._stop = False
        # True once the device's socket is gone ("robot hung up" vs "Gemini did").
        self.finished = False
        # Own single-thread pool: asyncio.run() only waits on the default executor,
        # and outbound audio shouldn't queue behind parked readers.
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="voice-rx")
        self.dropped = 0
        # When the robot last said someone talked over her (its own voice detector).
        self.barged_at: Optional[float] = None

    def start(self) -> "_DeviceReader":
        self._task = asyncio.create_task(self._run())
        return self

    def _receive_once(self):
        """One bounded blocking read. `_CLOSED` when the socket is finished."""
        try:
            return self._ws.receive(timeout=self._POLL_S)
        except Exception:      # ConnectionClosed, or the socket died under us
            return self._CLOSED

    async def _run(self) -> None:
        loop = asyncio.get_event_loop()
        while not self._stop:
            try:
                chunk = await loop.run_in_executor(self._pool, self._receive_once)
            except Exception:  # noqa: BLE001 — pool shut down under us; we are done
                break
            if chunk is self._CLOSED:
                break
            if chunk is None:
                continue       # quiet quarter second — the device is just silent
            if isinstance(chunk, str):
                if "barge_in" in chunk:
                    # The robot heard someone talk over her and already silenced her.
                    self.barged_at = time.monotonic()
                continue
            if not isinstance(chunk, (bytes, bytearray)):
                continue
            if self._q.full():
                try:
                    self._q.get_nowait()
                    self.dropped += 1
                except asyncio.QueueEmpty:
                    pass
            self._q.put_nowait(bytes(chunk))
        self.finished = True
        # Wake whoever is waiting so the bridge ends instead of hanging.
        if self._q.full():
            try:
                self._q.get_nowait()
            except asyncio.QueueEmpty:
                pass
        self._q.put_nowait(None)

    def pending(self) -> int:
        """Frames waiting to be read: empty means live, anything else is stored speech."""
        return self._q.qsize()

    async def frames(self):
        """Yield PCM frames, oldest buffered first, until the device goes away.

        Every frame is whole 16-bit samples: a socket message can end mid-sample (an odd
        length), and decoding that one crashed the call. The stray byte waits for the next.
        """
        carry = b""
        while True:
            chunk = await self._q.get()
            if chunk is None:
                return
            chunk = carry + chunk
            cut = len(chunk) - len(chunk) % 2
            chunk, carry = chunk[:cut], chunk[cut:]
            if chunk:
                yield chunk

    def stop(self) -> None:
        self._stop = True
        if self._task:
            self._task.cancel()
        # wait=False: the reader notices `_stop` within _POLL_S and exits by itself.
        self._pool.shutdown(wait=False)


# How long a refusal (a close frame arriving later) gets before a candidate counts as good.
_PROBE_SETTLE_S = 0.6


def _discover_live_models(client) -> tuple[str, ...]:
    """Ask the API which models do bidirectional audio right now (fallback when the static list is stale)."""
    try:
        models = list(client.models.list())
    except Exception as exc:  # noqa: BLE001 — discovery is a bonus, never a gate
        logger.warning("[voice_ws] could not list models: %s", exc)
        return ()

    found: list[str] = []
    for m in models:
        actions = (getattr(m, "supported_actions", None)
                   or getattr(m, "supported_generation_methods", None) or [])
        if "bidiGenerateContent" not in set(actions):
            continue
        name = str(getattr(m, "name", "") or "").removeprefix("models/")
        if name:
            found.append(name)

    if found:
        logger.info("[voice_ws] models the API reports as live-capable: %s",
                    ", ".join(found))
    else:
        logger.warning("[voice_ws] the API listed no live-capable model")
    return tuple(found)


async def _open_live_session(client, config):
    """Open the first Live model that actually accepts audio.

    connect() succeeding proves nothing (1007 arrives at the first audio frame), so
    each candidate is probed with real silence. Returns ``(cm, session,
    model_name, last_error)``; the manager is entered here once and the caller
    must ``__aexit__`` it.
    """
    from google.genai import types

    silence = types.Blob(data=b"\x00\x00" * 160, mime_type="audio/pcm;rate=16000")
    trusted = pinned_live_model()
    last_error: Exception | None = None

    # Known names first; discovery (a ~700 ms models.list()) runs only once they all refused.
    tried: set[str] = set()
    queue = list(live_model_candidates())
    asked = False
    while True:
        if not queue:
            if asked:
                break
            asked = True
            queue = [n for n in _discover_live_models(client) if n not in tried]
            if not queue:
                break
        candidate = queue.pop(0)
        if candidate in tried:
            continue
        tried.add(candidate)
        probe = client.aio.live.connect(model=candidate, config=config)
        try:
            session = await probe.__aenter__()
            await session.send_realtime_input(audio=silence)
            if candidate != trusted:
                # A model a real session already proved skips the wait (unpinned if it fails).
                await asyncio.sleep(_PROBE_SETTLE_S)
                await session.send_realtime_input(audio=silence)
        except Exception as exc:  # noqa: BLE001 — any refusal means "try the next"
            last_error = exc
            logger.warning("[voice_ws] live model %s refused: %s", candidate, exc)
                # A refused candidate may hold an open socket; close it (without
                # passing the exception, which would raise a bogus RuntimeError).
            try:
                await probe.__aexit__(None, None, None)
            except Exception:  # noqa: BLE001 — already failing; nothing to add
                logger.debug("[voice_ws] probe close failed", exc_info=True)
            continue
        return probe, session, candidate, None
    return None, None, "", last_error


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

    # Checked before the reader starts.
    if not GEMINI_API_KEY:
        logger.error("[voice_ws] GEMINI_API_KEY not set")
        _send_json(ws, {"type": "error", "msg": "server_error"})
        return

    # Start listening BEFORE the slow setup (see _DeviceReader). Everything below
    # is inside one try/finally so the reader's thread is never leaked; bound to
    # None first and constructed inside the try.
    reader: Optional["_DeviceReader"] = None
    _held = ""
    try:
        reader = _DeviceReader(ws).start()

        # الهوية بتتمرّر كوسيط: متغيّر السياق ما بيعبر لخيط المجمّع.
        _who = get_voice_identity()
        _channel = get_voice_channel()
        # التسخين بيستنّى لآخر المكالمة (شوف `prompt_prewarm.hold`).
        from app.utils import prompt_prewarm
        prompt_prewarm.hold(_who)
        _held = _who
        # الاسم والتعليمات وآخر المحادثات بيتقرّوا بالتوازي بالمجمّع (قراءات حاجبة)،
        # والاسم بينحطّ بسياق الحلقة قبل أول جملة.
        _loop = asyncio.get_event_loop()
        _t_seed = time.monotonic()
        _label, _base, _recent = await asyncio.gather(
            _loop.run_in_executor(None, resolve_speaker_label, _who),
            _loop.run_in_executor(None, _build_cached_instruction, _who, _channel),
            _loop.run_in_executor(None, load_recent_turns, _who),
        )
        set_voice_speaker_label(_label)
        _ms_seed = (time.monotonic() - _t_seed) * 1000
        system_instruction = with_recent_turns(_base, session_context(_recent))
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
            # بدون هدول التفريغ ما بيوصل، فالمحادثات الصوتية ما بتنحفظ بالذاكرة.
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),

            # Resumption (reconnect after GoAway with state intact) and context
            # compression keep long calls alive past Google's ~10/15-minute limits.
            context_window_compression=types.ContextWindowCompressionConfig(
                trigger_tokens=_COMPRESS_TRIGGER_TOKENS,
                sliding_window=types.SlidingWindow(
                    target_tokens=_COMPRESS_WINDOW_TOKENS),
            ),
        )
        # بلا تفكير: كان بيأخّر أول صوت ست ثواني ونص (صار ~3.7). التفكير للشات، مش للحكي.
        config_kwargs["thinking_config"] = types.ThinkingConfig(
            thinking_budget=0, include_thoughts=False)

        # نهاية الدور بتتقرّر عنا دايمًا (إلا بمكالمة التطبيق مع SANDY_APP_TURNS=gemini):
        # كاشف جيميناي ما بيلاقي صمت ببثّ الروبوت، فالردّ كان يوصل بعد ما اللوح سكّر.
        auto_turns = _APP_TURNS_BY_GEMINI and get_voice_channel() == _APP_CHANNEL
        if auto_turns:
            # مكالمة التطبيق: جيميناي بيقرّر — شوف `_APP_TURNS_BY_GEMINI`.
            config_kwargs["realtime_input_config"] = types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    disabled=False,
                    start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_LOW,
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
                    prefix_padding_ms=_APP_PREFIX_MS,
                    silence_duration_ms=_APP_SILENCE_MS,
                ),
            )
        else:
            config_kwargs["realtime_input_config"] = types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(disabled=True),
            )
        # The session outlives the connection: on GoAway we reconnect with the resumption handle.
        resume_handle: Optional[str] = None
        live_state: Dict[str, Any] = {"resume": None, "goaway": False}
        client = genai.Client(api_key=GEMINI_API_KEY)

        while True:
            config_kwargs["session_resumption"] = types.SessionResumptionConfig(
                handle=resume_handle)
            config = types.LiveConnectConfig(**config_kwargs)

            _t_dial = time.monotonic()
            cm, session, model_name, last_error = await _open_live_session(client, config)
            _ms_dial = (time.monotonic() - _t_dial) * 1000

            if not model_name:
                _send_json(ws, {"type": "error", "msg": "live_model_unavailable"})
                logger.error("[voice_ws] no live model accepted audio; last: %s", last_error)
                return

            remember_live_model(model_name)
            try:
                # وين راح وقت فتح المكالمة (المايك شغّال طول الوقت؛ مئات المللي = الكاش انكسر).
                logger.info(
                    "[voice_ws] session open: seed=%.0fms dial=%.0fms total=%.0fms "
                    "(model=%s gate=%s cached=%s) %s",
                    _ms_seed, _ms_dial, _ms_seed + _ms_dial, model_name, gate_on,
                    "yes" if _ms_seed < 400 else "no", remote,
                )

                if reader.dropped:
                    logger.warning(
                        "[voice_ws] setup took long enough to drop %d buffered frames",
                        reader.dropped,
                    )

                recent = _RecentAudio()
                t_in = asyncio.create_task(
                    _device_to_live_auto(reader, session, recent,
                                         live_state=live_state)
                    if auto_turns else
                    _device_to_live(reader, session, recent, verify=gate_on,
                                    live_state=live_state))
                t_out = asyncio.create_task(
                    _live_to_device(ws, session, recent, live_state))

                done, pending = await asyncio.wait(
                    [t_in, t_out],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                # When the robot stops sending (the normal end of a question), let
                # the reply finish, up to a bounded wait. When Gemini's side ends,
                # there's nothing left to wait for.
                if t_in in done and t_out in pending:
                    try:
                        await asyncio.wait_for(t_out, timeout=_REPLY_DRAIN_S)
                        logger.info("[voice_ws] device stopped sending; reply finished")
                    except asyncio.TimeoutError:
                        logger.warning(
                            "[voice_ws] reply still running %ds after the device went "
                            "quiet — cutting it", _REPLY_DRAIN_S)
                    except Exception:  # noqa: BLE001
                        logger.debug("reply drain ended with an error", exc_info=True)
                    done = {t_in, t_out}
                    pending = set()

                for t in pending:
                    t.cancel()
                    try:
                        await t
                    except (asyncio.CancelledError, Exception):  # noqa: BLE001
                        logging.getLogger(__name__).debug("ignoring non-critical error", exc_info=True)
                # Name which side ended and why (otherwise only the other task's CancelledError shows).
                for t in done:
                    side = "device→live" if t is t_in else "live→device"
                    if t.cancelled():
                        logger.info("[voice_ws] %s cancelled", side)
                    elif t.exception():
                        exc = t.exception()
                        logger.error("[voice_ws] %s failed: %r", side, exc,
                                     exc_info=exc)
                        # A refusal that got past the probe: unpin so the next call re-walks.
                        if "CONTENT_TYPE_AUDIO" in str(exc) or "1007" in str(exc):
                            forget_live_model(model_name)
                    else:
                        logger.info("[voice_ws] %s ended cleanly, closing session", side)
            finally:
                # What `async with` would have done.
                await cm.__aexit__(None, None, None)

            # Reconnect only if Gemini asked, the device is still there, and we have a handle.
            resume_handle = live_state.get("resume") or resume_handle
            if not (live_state.get("goaway") and resume_handle
                    and reader is not None and not reader.finished):
                break
            live_state["goaway"] = False
            logger.info("[voice_ws] reconnecting to the same session after "
                        "GoAway")

    except Exception as exc:
        logger.error("[voice_ws] Live session error (%s): %s", remote, exc)
        _send_json(ws, {"type": "error", "msg": "live_error"})
    finally:
        if reader is not None:
            reader.stop()
        if _held:
            from app.utils import prompt_prewarm
            prompt_prewarm.release(_held)


# الردّ بيوصل قطع متلاحقة، فثانيتين بلا ولا قطعة معناها المولّد وقف.
_REPLY_STALE_S = 2.0
# How long a barge_in from the robot vouches for the speech that follows it.
_BARGE_TRUST_S = 3.0
# من سكوت المستخدم لأول صوت منها، بنعتبرها «عم ترد» حتى لو ما وصل بايت.
_REPLY_WARMUP_S = 8.0


# اسم القناة لمكالمة التطبيق: بينحفظ مع كل جملة وبيفرّق مسار التطبيق عن الروبوت.
_APP_CHANNEL = "مكالمة التطبيق"
_ROBOT_CHANNEL = "الروبوت"

# سؤال ردّت عليه بس تفريغه رجع فاضي: بينحفظ هيك بدل النقط.
_UNHEARD_QUESTION = "(سؤال صوتي ما انكتب نصّه)"
_HAS_LETTERS = re.compile(r"[^\W\d_]")


def _she_has_not_spoken_yet(state: Dict[str, Any]) -> bool:
    """سكّرنا الدور، وهي لسا ما طلع منها ولا صوت."""
    closed = state.get("turn_closed_at")
    if closed is None:
        return False
    last_out = state.get("last_out_at")
    return last_out is None or float(last_out) < float(closed)


def _voiced(samples) -> bool:
    """A voice, not noise: the frame repeats itself at a speaking pitch (80–400 Hz).

    Engines, road and wind are broadband or far below that, so their energy alone
    can no longer interrupt a reply; a person talking to her still can.
    """
    import numpy as np

    x = samples.astype(np.float32)
    if x.size < 400:
        return False
    x -= x.mean()
    energy = float(np.dot(x, x))
    if energy <= 1e-3:
        return False
    ac = np.correlate(x, x, mode="full")[x.size - 1:]
    lo, hi = 16000 // 400, min(16000 // 80, x.size - 2)
    peak = lo + int(np.argmax(ac[lo:hi + 1]))
    # A real cycle peaks inside the range; a rumble too slow for a voice only slopes
    # down across it, so its highest point sits on the edge.
    if peak in (lo, hi) or ac[peak] < ac[peak - 1] or ac[peak] < ac[peak + 1]:
        return False
    return float(ac[peak]) / energy >= _VOICED_MIN


def _barge_bar_ms(state: Dict[str, Any]) -> float:
    """قدّيش لازم يحكي عشان نعتبرها مقاطعة.

    الحدّ بينزل (مش بينفتح) طالما ما طلع منها ولا صوت بعد إقفال الدور: وقفة التفكير
    بنصّ الجملة غالبًا أقصر من الحدّ الكامل، ومقاطعة ردّ ما بلّش أرخص.
    """
    return _CONTINUE_MIN_MS if _she_has_not_spoken_yet(state) else _BARGE_MIN_MS


def _she_is_really_answering(state: Dict[str, Any]) -> bool:
    """هل هي فعلًا بتردّ هلّق؟ (آخر قطعة صوت بعتناها، أو مهلة التحضير بعد إقفال الدور.)"""
    now = time.monotonic()
    last_out = state.get("last_out_at")
    if last_out is not None:
        if now - float(last_out) <= _REPLY_STALE_S:
            return True
    else:
        closed = state.get("turn_closed_at")
        if closed is not None and now - float(closed) <= _REPLY_WARMUP_S:
            return True
    state["replying"] = False          # ساكتة من زمان — الدور خلص عمليًا
    state.pop("last_out_at", None)
    state.pop("turn_closed_at", None)
    return False


async def _device_to_live_auto(reader: "_DeviceReader", session,
                               recent: "_RecentAudio", *,
                               live_state: Optional[Dict[str, Any]] = None) -> None:
    """مكالمة التطبيق بكاشف جيميناي: كل الصوت إله وهو بيقرّر الدور والمقاطعة.

    الشدّة بتنقاس هون للقياس بس («أول صوت بعد ما سكت»).
    """
    from google.genai import types
    import numpy as np

    state: Dict[str, Any] = live_state if live_state is not None else {}
    frames = 0
    sent = 0
    heard_ms = 0.0
    loudest = 0.0
    window: "deque[tuple[float, float]]" = deque()
    window_ms = 0.0

    async for chunk in reader.frames():
        samples = np.frombuffer(chunk, dtype="<i2")
        if samples.size == 0:
            continue
        rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))
        ms = samples.size / 16000 * 1000
        heard_ms += ms
        loudest = max(loudest, rms)
        if frames == 0:
            logger.info("[voice_ws] first frame from the app: %d bytes, %.0fms, "
                        "rms %.0f — Gemini decides the turns", len(chunk), ms, rms)

        window.append((ms, rms))
        window_ms += ms
        while window_ms > _VAD_FLOOR_MS and len(window) > _VAD_FLOOR_MIN_FRAMES:
            window_ms -= window.popleft()[0]
        if len(window) >= _VAD_FLOOR_MIN_FRAMES:
            room = min(min(r for _, r in window), _VAD_ROOM_MAX)
            if rms >= max(room * _VAD_FLOOR_FACTOR, _VAD_RMS_FLOOR):
                state["turn_closed_at"] = time.monotonic()

        recent.add(chunk)
        for i in range(0, len(chunk), _CHUNK_BYTES):
            piece = chunk[i:i + _CHUNK_BYTES]
            if piece:
                await session.send_realtime_input(
                    audio=types.Blob(data=piece, mime_type="audio/pcm;rate=16000"))
        frames += 1
        sent += len(chunk)

    logger.info("[voice_ws] device→live done: %d frames, %d bytes, "
                "%.1fs audio, %d frames dropped (heard %.1fs, loudest %.0f) "
                "— turns by Gemini",
                frames, sent, sent / 2 / 16000, reader.dropped,
                heard_ms / 1000, loudest)


async def _device_to_live(reader: "_DeviceReader", session, recent: "_RecentAudio",
                          *, verify: bool = True,
                          live_state: Optional[Dict[str, Any]] = None) -> None:
    """Stream device PCM to Live with manual turn control (our own VAD).

    Before closing a turn we verify the speaker and inject their persona.
    """
    from google.genai import types
    import numpy as np

    speaking = False
    silence_ms = 0.0
    utter_ms = 0.0

    frames = 0
    sent = 0
    heard_ms = 0.0
    # (مدة الإطار بالملي، شدّته): النافذة بالوقت، فاللوح والتطبيق بيغطّوا نفس المدة.
    window: "deque[tuple[float, float]]" = deque()
    window_ms = 0.0
    room: "deque[tuple[float, float]]" = deque()
    room_ms = 0.0
    threshold = float(_VAD_RMS_FLOOR)
    # قدّيش صار إلنا نسمع صوت وما فتحت البوابة ولا مرّة.
    quiet_ms = 0.0
    unstuck = False
    loudest = 0.0
    consumed = 0
    speech_ms = 0.0
    held: List[bytes] = []
    held_ms = 0.0
    # Of the held time, how much was a voice (pitched), not noise: only that interrupts her.
    held_voiced_ms = 0.0
    backlog = reader.pending()
    draining = backlog > _BACKLOG_FRAMES
    if draining:
        logger.info("[voice_ws] %d frames were buffered during setup — one turn, "
                    "not several", backlog)

    async def _send_audio(chunk: bytes) -> None:
        """Forward one device frame split to 20–40 ms chunks, so turns start and end earlier."""
        nonlocal frames, sent
        for i in range(0, len(chunk), _CHUNK_BYTES):
            piece = chunk[i:i + _CHUNK_BYTES]
            if not piece:
                continue
            await session.send_realtime_input(
                audio=types.Blob(data=piece, mime_type="audio/pcm;rate=16000")
            )
        frames += 1
        sent += len(chunk)
        if frames == 1:
            logger.info("[voice_ws] first audio frame forwarded to Gemini "
                        "(%d bytes, split into %d)", len(chunk),
                        max(1, -(-len(chunk) // _CHUNK_BYTES)))

    state: Dict[str, Any] = live_state if live_state is not None else {}

    async def _close_turn(reason: str) -> None:
        """End the user's turn and tell Gemini.

        While she is already answering, only a real interruption (long enough to be
        speech) closes it: every activity_end cancels the generation in progress.
        """
        nonlocal speaking, silence_ms, utter_ms, speech_ms
        # Measured in speech, not elapsed time (the closing silence is inside utter_ms).
        if state.get("replying") and _she_is_really_answering(state) \
                and speech_ms < _barge_bar_ms(state):
            logger.info("[voice_ws] ignoring a %.1fs blip while she is answering "
                        "(last audio from her %.1fs ago)", speech_ms / 1000,
                        time.monotonic() - float(state.get("last_out_at") or 0))
            speaking = False
            silence_ms = 0.0
            utter_ms = 0.0
            speech_ms = 0.0
            return
        if utter_ms >= _VAD_MIN_UTTER_MS:
            # This turn's own audio (16 kHz, 16-bit = 32 bytes a millisecond).
            await _learn_voice(session, recent.snapshot()[-int(utter_ms * 32):])
        if verify and utter_ms >= _VAD_MIN_UTTER_MS:
            await _verify_and_inject(session, recent.snapshot())
        await session.send_realtime_input(activity_end=types.ActivityEnd())
        state["replying"] = True
        # للقياس: من هون لأول صوت منها هو الانتظار اللي بيحسّه المستخدم.
        state["turn_closed_at"] = time.monotonic()
        logger.info("[voice_ws] turn closed after %.1fs of speech (%s)",
                    utter_ms / 1000, reason)
        speaking = False
        silence_ms = 0.0
        utter_ms = 0.0
        speech_ms = 0.0

    # Frames are pulled with a timeout, not iterated: the board stops sending when
    # the user stops, so a gap ends the turn. Never cancel the pull on timeout
    # (that would close the generator and end the call).
    stream = reader.frames().__aiter__()
    frame_task: Optional[asyncio.Task] = None
    # The pull task must never outlive this bridge, or an orphan eats frames
    # (or end-of-stream) from the next bridge after a reconnect.
    try:
        while True:
            if frame_task is None:
                frame_task = asyncio.ensure_future(stream.__anext__())
            finished_now, _ = await asyncio.wait({frame_task}, timeout=_SILENCE_GAP_S)
            if not finished_now:
                # A full gap with a turn open ends it, backlog or not.
                draining = False
                if speaking:
                    await _close_turn("device went quiet")
                continue
            frame_task = None
            try:
                chunk = finished_now.pop().result()
            except StopAsyncIteration:
                break

            consumed += 1
            samples = np.frombuffer(chunk, dtype="<i2")
            if samples.size == 0:
                continue
            rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))
            ms = samples.size / 16000 * 1000
            heard_ms += ms
            if consumed == 1:
                # مدة الإطار بتقول من وين إجا الصوت (لوح أو تطبيق).
                logger.info("[voice_ws] first frame from the device: "
                            "%d bytes, %.0fms, rms %.0f", len(chunk), ms, rms)

            # Speech = clearly above the room floor (with an absolute minimum). The
            # floor is the quietest moment in recent seconds, learned only while no
            # turn is open: the board now sends speech alone, so learning during
            # an utterance would raise the floor to the quietest word.
            if not speaking:
                window.append((ms, rms))
                window_ms += ms
                while window_ms > _VAD_FLOOR_MS and len(window) > _VAD_FLOOR_MIN_FRAMES:
                    window_ms -= window.popleft()[0]
                room.append((ms, rms))
                room_ms += ms
                while room_ms > _VAD_ROOM_MS and len(room) > _VAD_FLOOR_MIN_FRAMES:
                    room_ms -= room.popleft()[0]
                if len(window) >= _VAD_FLOOR_MIN_FRAMES:
                    quietest = min(r for _, r in window)
                    if not frames:
                        # ما فتحت البوابة ولا مرّة: الموجود ممكن يكون صوته هو.
                        quietest = min(quietest, _VAD_ROOM_MAX)
                    # شبكة الأمان: صوت متواصل بلا فتح بوابة معناها الأرضية هي الكلام نفسه.
                    if quiet_ms >= _VAD_STUCK_MS:
                        quietest = min(quietest, min(r for _, r in room))
                        if not unstuck:
                            unstuck = True
                            logger.warning(
                                "[voice_ws] %.0fs of audio and the gate never "
                                "opened — refloored from %.0f to %.0f "
                                "(loudest frame %.0f)",
                                quiet_ms / 1000, threshold,
                                max(quietest * _VAD_FLOOR_FACTOR, _VAD_RMS_FLOOR),
                                loudest)
                    threshold = max(quietest * _VAD_FLOOR_FACTOR, _VAD_RMS_FLOOR)
            # Nothing is speech until the room is known (the board's preroll is the room).
            is_speech = (len(window) >= _VAD_FLOOR_MIN_FRAMES
                         and rms >= threshold)
            loudest = max(loudest, rms)
            # عدّ الصمت بس لحد أول فتح للبوابة.
            if is_speech or frames:
                quiet_ms = 0.0
            else:
                quiet_ms += ms

            if is_speech and not speaking:
                # Only a voice opens a turn: a door, the TV, a fan opened one before and
                # she answered the noise («sorry about that…») or cut her own reply. Frames
                # are held until enough of them are voiced; while she answers (activity_start
                # interrupts her) the bar is higher.
                # The robot's {"type":"barge_in"}: it is sure, so no bar of our own.
                barged = time.monotonic() - (getattr(reader, "barged_at", None) or -1e9) < _BARGE_TRUST_S
                answering = (state.get("replying") and _she_is_really_answering(state)
                             and not barged)
                held.append(chunk)
                held_ms += ms
                if _voiced(samples):
                    held_voiced_ms += ms
                while held_ms > _HELD_MS_MAX and len(held) > 1:
                    # The dropped frame's time leaves with it.
                    held_ms -= len(held.pop(0)) / 2 / 16000 * 1000
                held_voiced_ms = min(held_voiced_ms, held_ms)
                if held_voiced_ms < (_barge_bar_ms(state) if answering else _ONSET_VOICED_MS):
                    continue
                if answering:
                    logger.info("[voice_ws] %.1fs of speech while she answers — "
                                "taking it as an interruption", held_ms / 1000)

                # Speech onset: open an activity. Keep `recent` (verification needs a few seconds).
                speaking = True
                silence_ms = 0.0
                utter_ms = 0.0
                await session.send_realtime_input(activity_start=types.ActivityStart())
                # فتح الدور بيلغي التوليد، فنزّل العلامة وإلا الإقفال الجاي بينبلع.
                state["replying"] = False
                for pending in held:
                    await _send_audio(pending)
                held.clear()
                held_ms = 0.0
                held_voiced_ms = 0.0
            elif not speaking and held:
                # The noise died before it became a sentence.
                held.clear()
                held_ms = 0.0
                held_voiced_ms = 0.0

            if speaking:
                recent.add(chunk)
                await _send_audio(chunk)
                utter_ms += ms
                # Loud is not talking: the TV or a fan kept a turn open nine seconds after
                # the question ended. Only a voice holds it; anything else counts as quiet.
                talking = is_speech and _voiced(samples)
                if talking:
                    speech_ms += ms
                silence_ms = 0.0 if talking else silence_ms + ms

                # A startup backlog is one question, not four: no turn closes until
                # the frames queued at call start are consumed (counted once, in
                # consumed frames, then lifted for good).
                if draining and consumed >= backlog:
                    draining = False
                    if backlog:
                        logger.info("[voice_ws] %d buffered frames are through — "
                                    "live now", backlog)
                if draining:
                    continue

                if utter_ms >= _VAD_MAX_UTTER_MS:
                    # ربع دقيقة والدور مفتوح: خلّي السؤال يوصل بدل ما يضلّ مفتوح.
                    await _close_turn("long enough to be a question")
                elif silence_ms >= _VAD_SILENCE_MS:
                    # Kept beside the gap test: old firmware streams the room with no gaps.
                    await _close_turn("quiet frames")
            # Idle silence before any speech: don't forward it, saves bandwidth.
    finally:
        if frame_task is not None:
            frame_task.cancel()

    # `consumed` و`heard_ms` بيفرّقوا «ما وصل صوت» عن «وصل وما عدّى البوابة».
    logger.info("[voice_ws] device→live done: %d frames, %d bytes, "
                "%.1fs audio, %d frames dropped "
                "(heard %d frames / %.1fs, loudest %.0f, threshold %.0f)",
                frames, sent, sent / 2 / 16000, reader.dropped,
                consumed, heard_ms / 1000, loudest, threshold)


async def _live_to_device(ws, session, recent: "_RecentAudio",
                          live_state: Optional[Dict[str, Any]] = None) -> None:
    """Relay Gemini Live responses to the device and handle tool calls.

    `live_state` carries back the latest resumption handle and whether the server said it's hanging up.
    """
    if live_state is None:
        live_state = {}
    from google.genai import types


    loop = asyncio.get_event_loop()
    gate_on = _speaker_gate_enabled()

    # One thread for everything written to the device: strict FIFO, never starved.
    tx = ThreadPoolExecutor(max_workers=1, thread_name_prefix="voice-tx")

    # الأدوات بمجمعها (اتنين: ممكن أداتين بنفس الدور) عشان ما تأخّر الصوت.
    tools_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="voice-tool")

    # ── Keeping the socket alive ─────────────────────────────────────────────
    # Heroku's router closes a connection with <~50 bytes in 55 s (H15); healthy
    # voice sessions go quiet that long all the time.
    _KEEPALIVE_S = 20.0
    _last_send = time.monotonic()

    async def send_bytes(data: bytes) -> None:
        nonlocal _last_send
        _last_send = time.monotonic()
        await loop.run_in_executor(tx, ws.send, data)

    async def send_msg(obj: Dict[str, Any]) -> None:
        nonlocal _last_send
        _last_send = time.monotonic()
        await loop.run_in_executor(tx, _send_json, ws, obj)

    async def _keepalive() -> None:
        """Send a tiny frame only when the socket has been quiet too long."""
        while True:
            await asyncio.sleep(_KEEPALIVE_S / 2)
            if time.monotonic() - _last_send >= _KEEPALIVE_S:
                try:
                    await send_msg({"type": "ping"})
                except Exception:  # noqa: BLE001 — a dead socket ends the session anyway
                    return

    _user_buf: List[str] = []
    _sandy_buf: List[str] = []

    # `_first`: first message of any kind from Gemini; `_audio_out`: what reached the speaker.
    _seen = {"any": False, "user_text": False, "audio_out": 0}
    # The mood her face shows for this reply (robot only), sent again only when it changes.
    _face = {"mood": ""}
    _audio = {"at": time.monotonic(), "chunks": 0, "wait": 0.0,
              "send": 0.0, "worst": 0.0}
    _turn_audio = {"n": 0}

    async def _handle(response) -> bool:
        """Process one Live response; True stops the session. Relays audio, saves STM, gates tools."""

        if not _seen["any"]:
            _seen["any"] = True
            logger.info("[voice_ws] first response from Gemini")

        # Keep the resumption handle every time it changes.
        update = getattr(response, "session_resumption_update", None)
        if update is not None and getattr(update, "resumable", False):
            handle = getattr(update, "new_handle", "")
            if handle:
                live_state["resume"] = handle

        # The warning that the connection is ending.
        away = getattr(response, "go_away", None)
        if away is not None:
            live_state["goaway"] = True
            logger.info("[voice_ws] GoAway from Gemini (%s left) — will reconnect",
                        getattr(away, "time_left", "?"))

        # Capture user speech transcript
        if response.server_content and response.server_content.input_transcription:
            t = response.server_content.input_transcription.text
            if t:
                if not _seen["user_text"]:
                    _seen["user_text"] = True
                    logger.info("[voice_ws] Gemini heard the user (first "
                                "transcript fragment)")
                _user_buf.append(t)

        # Sandy's transcript (native-audio models put no text in model_turn parts).
        if response.server_content and response.server_content.output_transcription:
            t = response.server_content.output_transcription.text
            if t:
                _sandy_buf.append(t)
                if get_voice_channel() == _ROBOT_CHANNEL:
                    mood = face.mood_of("".join(_sandy_buf))
                    if mood and mood != _face["mood"]:
                        _face["mood"] = mood
                        await send_msg({"type": "mood", "mood": mood})

        # Barge-in: tell the device to drop its buffered audio.
        if response.server_content and response.server_content.interrupted:
            # ونزّل علامة «عم ترد» هون كمان، وإلا بتضلّ مرفوعة وبتنبلع كل جملة بعدها.
            live_state["replying"] = False
            live_state.pop("last_out_at", None)
            _face["mood"] = ""
            await send_msg({"type": "interrupted"})

        # Audio plus text response: relay the audio, capture the text.
        if response.server_content and response.server_content.model_turn:
            for part in response.server_content.model_turn.parts:
                if part.inline_data and part.inline_data.data:
                    if not _seen["audio_out"]:
                        logger.info("[voice_ws] first reply audio → device")
                    _seen["audio_out"] += len(part.inline_data.data)
                    live_state["last_out_at"] = time.monotonic()
                    _turn_audio["n"] += len(part.inline_data.data)
                    # `wait` (nothing to send) + `send` vs the audio's duration
                    # shows whether stutter is Gemini, this dyno, or the link.
                    _now = time.monotonic()
                    _wait = _now - _audio["at"]
                    # أول صوت بعد ما يسكت المستخدم (مرة بكل دور).
                    _closed = (live_state or {}).pop("turn_closed_at", None)
                    # القطعة الأولى وصلت: من هلّق الحكم لآخر صوت، مش للمهلة.
                    if _closed is not None:
                        logger.info("[voice_ws] first audio %.0fms after the user stopped",
                                    (_now - _closed) * 1000)
                    await send_bytes(part.inline_data.data)
                    _audio["at"] = time.monotonic()
                    _audio["chunks"] += 1
                    _audio["wait"] += _wait
                    _audio["send"] += _audio["at"] - _now
                    _audio["worst"] = max(_audio["worst"], _wait)
                if part.text:
                    _sandy_buf.append(part.text)

        # Turn complete: persist the turn for cross-platform memory only.
        if response.server_content and response.server_content.turn_complete:
            live_state["replying"] = False
            # Concatenated, not space-joined: fragments aren't words and carry
            # their own spaces (this text is stored as memory).
            user_text = "".join(_user_buf).strip()
            sandy_text = "".join(_sandy_buf).strip()
            done: Dict[str, Any] = {"type": "end_turn"}
            if get_voice_channel() == _ROBOT_CHANNEL and sandy_text:
                # The face she keeps for a moment after the reply, then back to listening.
                done["mood"] = face.mood_of(sandy_text) or face.AFTER_DEFAULT
            _face["mood"] = ""
            await send_msg(done)
            if user_text and sandy_text and not _HAS_LETTERS.search(user_text):
                # التفريغ رجع نقط: ما منحفظ النقط كأنها سؤاله.
                logger.warning("[voice_ws] the transcript of the question came "
                               "back with no words (%r) — saved as unheard",
                               user_text[:40])
                user_text = _UNHEARD_QUESTION

            # Save the turn for shared memory; never re-inject history into the live
            # session (native audio answers injected turns). heard vs replied_audio
            # separates "heard but silent" from "never heard".
            logger.info("[voice_ws] turn done: heard=%r replied=%d chars, "
                        "%d bytes of audio (%.1fs)",
                        user_text[:120], len(sandy_text), _turn_audio["n"],
                        _turn_audio["n"] / 2 / 24000)
            _turn_audio["n"] = 0
            if user_text and sandy_text:
                # مش `await`: كتابة القاعدة ما لازم توقف بثّ الصوت.
                loop.run_in_executor(None, _save_voice_turn, user_text, sandy_text,
                                     get_voice_identity(), get_voice_channel())

            _user_buf.clear()
            _sandy_buf.clear()

        # Tool calls: dispatch them and return the result to Live.
        if response.tool_call:
            # للتطبيق بس: «لحظة، عم دوّر» وقت الأداة بدل ما تبيّن معلّقة.
            if get_voice_channel() == _APP_CHANNEL:
                await send_msg({"type": "working"})
            fn_responses: List[types.FunctionResponse] = []
            for fc in response.tool_call.function_calls:
                # V4.4–V4.5: أمر حسّاس + البوابة مفعّلة → تأكّد إنه صوت المالك أولاً.
                if gate_on and _is_sensitive_call(fc.name, dict(fc.args or {})):
                    verified = await loop.run_in_executor(
                        None, _verify_owner, recent.snapshot(), get_voice_identity()
                    )
                    if verified is None:
                        fn_responses.append(types.FunctionResponse(
                            id=fc.id, name=fc.name,
                            response={"output": (
                                "[لم يُنفَّذ] التحقق من الصوت مش جاهز هلّق. لا تنفّذي "
                                "الأمر — قولي إنك مش قادرة تتأكدي من صوته هلّق، "
                                "وخلّيه يجرّب كمان شوي."
                            )},
                        ))
                        continue
                    if not verified:
                        fn_responses.append(types.FunctionResponse(
                            id=fc.id, name=fc.name,
                            response={"output": (
                                "ما قدرت أتأكد إنه صوتك. لا تنفّذي الأمر — "
                                "اسألي بلطف: مين معي؟"
                            )},
                        ))
                        continue
                # Deletes and bulk changes hold for `confirm` inside the brain.
                # The identity travels with the tool call.
                result = await loop.run_in_executor(
                    tools_pool, _dispatch_tool, fc.name,
                    dict(fc.args or {}), get_voice_identity()
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

    # receive() yields one turn then ends, so loop across turns; try/finally so
    # a cancelled task still returns its threads.
    ka = asyncio.create_task(_keepalive())
    try:
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
                logger.info(
                    "[voice_ws] Live receive loop ended: %s "
                    "(heard user=%s, any response=%s, reply audio=%d bytes)",
                    exc, _seen["user_text"], _seen["any"], _seen["audio_out"])
                if _audio["chunks"]:
                    # 24 kHz 16-bit: if `audio` < `wait`, the listener hears a bad line.
                    logger.info(
                        "[voice_ws] reply timing: %d chunks, %.1fs audio, "
                        "%.1fs waiting (worst gap %.2fs), %.2fs sending",
                        _audio["chunks"], _seen["audio_out"] / 2 / 24000,
                        _audio["wait"], _audio["worst"], _audio["send"])
                break
    finally:
        ka.cancel()
        tx.shutdown(wait=False)
        tools_pool.shutdown(wait=False)


# Helpers

def _send_json(ws, payload: Dict[str, Any]) -> None:
    try:
        ws.send(json.dumps(payload, ensure_ascii=False))
    except Exception:
        logging.getLogger(__name__).debug("ignoring non-critical error", exc_info=True)
