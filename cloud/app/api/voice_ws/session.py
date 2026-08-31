"""voice_ws session."""
from __future__ import annotations
import logging

import asyncio
import hashlib
import hmac as _hmac
import json
import os
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
    _SENSITIVE_TOOLS,
    _VAD_SILENCE_MS,
    _BACKLOG_FRAMES,
    _BARGE_MIN_MS,
    _CHUNK_BYTES,
    _SILENCE_GAP_S,
    _COMPRESS_TRIGGER_TOKENS,
    _COMPRESS_WINDOW_TOKENS,
    _VAD_FLOOR_FACTOR,
    _VAD_FLOOR_FRAMES,
    _VAD_FLOOR_MIN_FRAMES,
    _VAD_RMS_FLOOR,
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
    get_voice_channel,
    get_voice_identity,
    resolve_speaker_label,
    set_voice_speaker_label,
    set_voice_channel,
    set_voice_identity,
)
from app.api.voice_ws.tools import (
    _build_live_tools,
    _build_system_instruction,
    _dispatch_tool,
    _make_dispatcher,
)


# How long a reply may keep going after the robot stops sending audio.
#
# This is the gap between "she finished the question" and "she finished the
# answer", and it is normal — Gemini streams the reply while the device is
# silent. Twenty seconds covers any real answer; past that the stream is stuck
# and holding the session open only delays the next question.
_REPLY_DRAIN_S = 20


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
            # **أي حساب مسجّل، مش «المالك» وبس.**
            #
            # كان مقبولًا لمّا كان في مستخدم واحد ومتغيّر بيئة اسمه المالك. ومع
            # الدخول بأبل وجوجل، «المالك» بطّل يكون شخصًا — صار حسابًا قديمًا
            # ما حدا بيدخل فيه، والمكالمة الصوتية بتنرفض لكل زبون جديد.
            #
            # والعزل ما ضعف: الهوية بتنحفظ للجلسة، وكل قراءة وكتابة بعدها
            # بتنقيّد فيها. يعني كل واحد بيحكي مع ساندي تبعته وذاكرته هو.
            if claims and claims.get("role") in ("owner", "user"):
                uid = str(claims.get("user_id") or "")
                if not uid:
                    ws.send(json.dumps({"type": "error", "msg": "auth_fail"}))
                    return False
                set_voice_identity(uid)
                set_voice_channel("مكالمة التطبيق")
                ws.send(json.dumps({"type": "auth_ok"}))
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

            # **الروبوت بيحكي باسم صاحبه.**
            #
            # المفتاح بيثبت إنه لوح حقيقي، مش مين صاحبه. والصاحب مكتوب بالوحدة
            # من ساعة الربط — فمنسأل الوحدة بدل ما نفترض إنه في مالك واحد
            # بمتغيّر بيئة، وهي فرضية بتنكسر عند تاني زبون.
            #
            # ولوح ما حدا ربطه بيحكي، بس بلا ذاكرة شخص — لأنه فعلًا ما إله
            # شخص بعد. وهاد أحسن من إنه ياخد ذاكرة حدا تاني.
            from app.features.node_store import get_node_any_tenant
            node = get_node_any_tenant(device_id) or {}
            owner = str(node.get("user_id") or "")
            if owner:
                set_voice_identity(owner)
            else:
                logger.warning("[voice_ws] device %s is not paired to anyone", device_id)
            set_voice_channel("الروبوت")

            # **هون بيتسلّم اللوح مفتاحه الخاص بالوسيط.**
            #
            # كل لوح لسا بينباع بنفس مستخدم وكلمة سرّ الوسيط، مكتوبين بالكود —
            # يعني أي زبون بيقدر يسمع مواضيع أي زبون تاني. هاي المصافحة هي
            # المكان الصح للتسليم لأنها موثّقة بمفتاح **مش** مفتاح الوسيط، فهي
            # بتضل شغّالة بعد ما ينلغي المفتاح المشترك. تسليمه ع الوسيط نفسه
            # كان بيخلّي المفتاح المشترك لازم للأبد.
            #
            # ولوح ما إله سطر بالجدول ما بياخد إشي وبيضل ع مفتاحه الحالي: إعداد
            # ناقص لازم يخلّي الروبوتات الشغّالة شغّالة، مش يوقّفها.
            reply: Dict[str, Any] = {"type": "auth_ok"}
            try:
                from app.features.broker_creds import creds_for_device
                creds = creds_for_device(device_id)
                if creds:
                    reply["broker"] = creds
            except (ImportError, ValueError, TypeError, AttributeError) as exc:
                # التسليم إضافة ع المصافحة، مش شرط فيها. عطل هون بيخلّي اللوح
                # ع مفتاحه القديم — وهاد أهون بكتير من جلسة صوت بتفشل.
                logger.warning("[voice_ws] broker credential lookup failed for %s: %s",
                               device_id, exc)

            ws.send(json.dumps(reply))
            logger.info("[voice_ws] auth OK device=%s owner=%s remote=%s creds=%s",
                        device_id, owner or "—", remote,
                        "sent" if "broker" in reply else "—")
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

class _DeviceReader:
    """Drains the device socket from the moment the session starts.

    The robot streams audio the instant it is authenticated, but opening the Live
    session first has to build the system instruction, pull memory and hand-shake
    with Gemini — several seconds during which nothing was reading the socket. Its
    frames piled up, the robot's own write blocked past its one-second timeout,
    and it tore the call down before a single word got through. So reading starts
    here, immediately, and the buffered audio is handed over once Live is up.

    The buffer is bounded and drops the OLDEST frame when full: if setup runs long
    the recent words matter, stale ones don't.
    """

    _FRAME_MS = 20  # the robot sends ~20ms of PCM per frame

    # How long one blocking read is allowed to wait before coming up for air.
    #
    # **This number is why sessions stopped hanging.** The read used to have no
    # deadline at all, and a read with no deadline returns only when the device
    # sends something or the socket breaks. A robot that has finished speaking
    # and is waiting for an answer sends nothing — so the read sat there, and
    # the worker thread behind it sat there with it.
    #
    # asyncio.run() is what turned that into an outage. On the way out it calls
    # loop.shutdown_default_executor(), which waits for every executor thread to
    # finish. Measured: a session whose work ended in 0.2s did not return for a
    # full 6s, purely waiting on that one parked thread. In production the wait
    # is not six seconds — it is until the robot speaks again or TCP gives up.
    #
    # gunicorn runs 2 workers x 8 threads. Every hung session holds one of the
    # sixteen. Enough of them and a new voice connection has nowhere to land:
    # the robot connects, waits, gets nothing, and reboots itself. That is
    # exactly "it answers once and then ignores me twice".
    #
    # A quarter second is short enough that a stopped reader is gone before
    # anyone notices, and long enough that idle polling costs nothing.
    _POLL_S = 0.25

    # Returned by the read helper when the socket is gone, so a real close is
    # never confused with a quiet quarter second. simple_websocket returns None
    # on timeout and raises ConnectionClosed on close — two very different
    # things that the old code, having no timeout, could treat as one.
    _CLOSED = object()

    def __init__(self, ws, buffer_ms: int = 8000):
        self._ws = ws
        self._q: asyncio.Queue = asyncio.Queue(maxsize=buffer_ms // self._FRAME_MS)
        self._task: Optional[asyncio.Task] = None
        self._stop = False
        # True once the device's socket is gone. The reconnect decision needs to
        # know the difference between "Gemini hung up" and "the robot did".
        self.finished = False
        # Its own thread, not the shared default executor.
        #
        # Two reasons. asyncio.run() only waits for the *default* executor, so a
        # reader on its own pool can never stall shutdown again even if this
        # code grows a new way to block. And audio going out to the device also
        # needs a thread — sharing one pool meant every outbound chunk queued
        # behind however many readers were parked, which is what made her voice
        # arrive in pieces.
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="voice-rx")
        self.dropped = 0

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
        """Frames waiting to be read — how far behind the bridge is, exactly.

        Timing cannot answer this. A first attempt compared the audio clock to
        the wall clock, and a device streaming in real time keeps whatever lead
        it started with forever, so the "still catching up" test was true for
        the whole call and no turn was ever closed. The queue knows: empty means
        live, anything else means there is stored speech still to hand over.
        """
        return self._q.qsize()

    async def frames(self):
        """Yield PCM frames, oldest buffered first, until the device goes away."""
        while True:
            chunk = await self._q.get()
            if chunk is None:
                return
            yield chunk

    def stop(self) -> None:
        self._stop = True
        if self._task:
            self._task.cancel()
        # wait=False on purpose: the reader thread notices `_stop` within
        # _POLL_S and exits by itself. Blocking here would put back the very
        # stall this class was rewritten to remove.
        self._pool.shutdown(wait=False)


# How long a refusal is given to come back before a candidate counts as good.
#
# **A send that returns is not a send that was accepted.** The 1007 is a close
# frame that arrives afterwards, so the first probe declared the model healthy,
# handed it a working session, and the real audio hit the same refusal eight
# seconds later. Waiting and then sending a second frame is the whole test: if
# the first was refused, the socket is shut and the second raises.
_PROBE_SETTLE_S = 0.6


def _discover_live_models(client) -> tuple[str, ...]:
    """Ask the API which models actually do bidirectional audio, right now.

    **The list in `_config` went stale all at once.** Every name in it came back
    `1008 ... is not found for API version v1beta, or is not supported for
    bidiGenerateContent`, and the one in the config var connected and then
    refused audio. Google renames these faster than anyone deploys, so a
    hardcoded list is a countdown, not a fix — it works until it does not, and
    when it stops, voice stops with it and nothing says why.

    The service knows the answer. This asks for it, and the static list becomes
    what it should always have been: a fast path, not the only path.
    """
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

    **`connect()` succeeding proves nothing.** The refusal that took voice down
    in production — `1007 CONTENT_TYPE_AUDIO is not supported` — arrived at the
    *first audio frame*, long after the handshake and the memory seed had been
    logged as fine. So the probe is a real one: send a frame of silence, and
    treat a close as "this model is not it".

    Returns ``(cm, session, model_name, last_error)``. **The caller owns the
    manager and must `__aexit__` it — it is entered here, exactly once.** The
    first cut of this kept the already-opened manager and then wrote
    ``async with cm:`` over it. `contextlib` deletes the arguments it needs on
    the first entry, so the second raised ``'_AsyncGeneratorContextManager'
    object has no attribute 'args'`` and every call died right after the seed.
    """
    from google.genai import types

    silence = types.Blob(data=b"\x00\x00" * 160, mime_type="audio/pcm;rate=16000")
    trusted = pinned_live_model()
    last_error: Exception | None = None

    # The known names first — they are usually right and cost nothing to try.
    # Whatever the service itself reports as live-capable goes after them, so a
    # list that has gone stale costs one round of failures rather than the
    # feature.
    # **Discovery is the fallback, so it is not run until it is the fallback.**
    #
    # Building the list eagerly called `models.list()` on every single call —
    # about seven hundred milliseconds of network before the first candidate had
    # even been tried, on a path where the microphone is recording into a buffer
    # the whole time. The known names go first, and the service is only asked
    # when every one of them has refused.
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
                # A model a real session already proved skips the wait; anything
                # else pays for the answer. `forget_live_model` takes the pin
                # away again the moment a proven one stops working, so trusting
                # it cannot outlive the evidence.
                await asyncio.sleep(_PROBE_SETTLE_S)
                await session.send_realtime_input(audio=silence)
        except Exception as exc:  # noqa: BLE001 — any refusal means "try the next"
            last_error = exc
            logger.warning("[voice_ws] live model %s refused: %s", candidate, exc)
            # A refused candidate can still hold an open socket — the refusal
            # lands after the handshake. Close it, or every retry leaks one.
            #
            # **Closed, not blamed.** Passing the exception in re-raises it
            # inside the SDK's generator, which then does not stop, and
            # `contextlib` turns that into `RuntimeError: generator didn't stop
            # after athrow()` — a second, invented failure on top of the real
            # one, printed with a traceback that points at the cleanup instead
            # of the cause.
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

    # Checked before the reader starts, not after: there is no point owning a
    # thread in order to discover a config value.
    if not GEMINI_API_KEY:
        logger.error("[voice_ws] GEMINI_API_KEY not set")
        _send_json(ws, {"type": "error", "msg": "server_error"})
        return

    # Start listening BEFORE the slow setup below — see _DeviceReader.
    #
    # **Everything from here down is inside one try/finally.** The reader owns a
    # thread and a single-worker executor the moment `start()` returns, and the
    # `finally` that gives them back used to begin much lower, at the Live
    # connect. So any return or raise in between — the missing key above, or a
    # `_build_system_instruction` that threw — leaked one thread and one
    # executor per connection *attempt*, and a robot that retries after a
    # failure leaks one per retry. Gunicorn has sixteen threads in total. That
    # is "she answers once and then ignores me", arriving by a second route.
    #
    # Bound to None first, and constructed *inside* the try: `__init__` builds
    # the executor before `start()` returns, so a raise between the two would
    # leak a pool that nothing holds a reference to.
    reader: Optional["_DeviceReader"] = None
    try:
        reader = _DeviceReader(ws).start()

        # **الهوية بتسافر مع النداء، مش بتنستنّى بالخيط.**
        #
        # `run_in_executor` بيشغّل هالدالة ع خيط تاني، ومتغيّر السياق ما بيعبر
        # لهناك. فلو دوّرت عليه هناك بتلاقيه فاضي — وهاد اللي صار حرفيًّا: المصافحة
        # حلّت المالك صح، وبناء التعليمات ع خيط تاني قال «جلسة مجهولة».
        #
        # وتمريره كوسيط بيشيل السؤال من أصله بدل ما يحاول يوصّل السياق.
        _who = get_voice_identity()
        # **والاسم كمان لازم ينحلّ هون، ع الحلقة.**
        #
        # `_speaker_directive` بينشغّل بآخر كل جملة، منتظَر ع نفس الحلقة اللي
        # بتمرّر الصوت. حلّ الاسم كسول، ولو انحلّ جوّا `run_in_executor` بينحفظ
        # بسياق خيط المجمّع — والحلقة بتضلّ فاضية، فبتدفع قراءة قاعدة بيانات
        # بأول جملة بالضبط: قبل أول ردّ، بأسوأ مكان ممكن. سطر هون بيخلّيه محلول
        # قبل ما تبلّش أي جملة.
        # **بالمجمّع، مش ع الحلقة.** `voice_speaker_label` بتقرا من مونغو، وهاي
        # قراءة حاجبة — نداؤها هون مباشرةً كان بينقل التعثّر من أول جملة لبداية
        # الجلسة، مش بيشيله، والقارئ بيكون عم يخزّن صوت وقتها. بننادي `_resolve`
        # بالمجمّع وبنحطّ الناتج بسياق الحلقة، فالقيمة موجودة قبل أي جملة.
        _loop = asyncio.get_event_loop()
        set_voice_speaker_label(
            await _loop.run_in_executor(None, resolve_speaker_label, _who))
        system_instruction = await _loop.run_in_executor(
            None, _build_system_instruction, _who
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

            # **A call that lasts is a call that survives the connection.**
            #
            # Google's own limits, and none of them were handled here: a Live
            # connection lives about ten minutes, an audio session dies at
            # fifteen without compression, and the server sends `GoAway` shortly
            # before it hangs up. So a long conversation ended by itself, mid
            # sentence, with nothing in the log that looked like a failure —
            # which is the same thing the owner reports as "she stops answering".
            #
            # Resumption keeps the session's state server-side for a day and
            # hands back a token to reconnect with; compression slides a window
            # over the oldest turns instead of hitting the wall. Together they
            # are what makes "always answers" a property rather than a hope.
            context_window_compression=types.ContextWindowCompressionConfig(
                trigger_tokens=_COMPRESS_TRIGGER_TOKENS,
                sliding_window=types.SlidingWindow(
                    target_tokens=_COMPRESS_WINDOW_TOKENS),
            ),
        )
        # **نهاية الدور بتتقرّر عنا، دايمًا.**
        #
        # كان الكشف التلقائي شغّال لمّا التحقّق مطفّى، وهاد بالضبط اللي خلّاها
        # «ما بتردّ». اللوح بيبثّ صوت الغرفة بلا توقّف، فما بيوصل جيميناي صمت
        # يعتبره نهاية كلام — وبيضلّ مستني. باللوج ظهر إنّ أوّل ردّ منه بيجي
        # **ثانية ونص بعد ما اللوح سكّر الاتصال**، مش بعد ما المستخدم سكت:
        #
        #     21:22:41.96  device→live done        ← اللوح قطع
        #     21:22:43.53  first response from Gemini
        #     21:22:46.02  first reply audio → device
        #
        # واللوح بيستنّى تمان ثواني بس بعد آخر كلمة (`VOICE_SESSION_IDLE_MS`)،
        # فالردّ كان بيوصل لسمّاعة مسكّرة — كل مرة، من غير استثناء.
        #
        # عنّا كاشف صمت شغّال أصلاً بمسار التحقّق. التحقّق من هوية المتكلّم
        # والتحكّم بنهاية الدور مسألتين منفصلتين، وربطهن ببعض هو الغلط: التحقّق
        # اختياري، ونهاية الدور لأ.
        config_kwargs["realtime_input_config"] = types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(disabled=True),
        )
        # **The session outlives the connection.**
        #
        # A Live connection lasts about ten minutes and the server sends
        # `GoAway` shortly before it closes one. Nothing here listened, so a
        # long conversation simply stopped — mid sentence, with a clean-looking
        # log — and from the room that is indistinguishable from her deciding
        # to ignore him. The handle Google hands back reconnects to the same
        # session with its memory intact, so the reconnect is invisible.
        resume_handle: Optional[str] = None
        live_state: Dict[str, Any] = {"resume": None, "goaway": False}
        client = genai.Client(api_key=GEMINI_API_KEY)
        dispatcher = _make_dispatcher()

        while True:
            config_kwargs["session_resumption"] = types.SessionResumptionConfig(
                handle=resume_handle)
            config = types.LiveConnectConfig(**config_kwargs)

            cm, session, model_name, last_error = await _open_live_session(client, config)

            if not model_name:
                _send_json(ws, {"type": "error", "msg": "live_model_unavailable"})
                logger.error("[voice_ws] no live model accepted audio; last: %s", last_error)
                return

            remember_live_model(model_name)
            try:
                logger.info(
                    "[voice_ws] Gemini Live session opened for %s (gate=%s, model=%s)",
                    remote, gate_on, model_name
                )

                if reader.dropped:
                    logger.warning(
                        "[voice_ws] setup took long enough to drop %d buffered frames",
                        reader.dropped,
                    )

                recent = _RecentAudio()
                t_in = asyncio.create_task(
                    _device_to_live(reader, session, recent, verify=gate_on,
                                    live_state=live_state))
                t_out = asyncio.create_task(
                    _live_to_device(ws, session, dispatcher, recent, live_state))

                done, pending = await asyncio.wait(
                    [t_in, t_out],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                # The two directions are not equals, and treating them as equals is
                # what cut her off mid-sentence.
                #
                # device→live ending means the robot stopped sending audio. That is
                # the *normal* end of a question — and Gemini is very often still
                # speaking the answer when it happens. Cancelling the other side
                # right there threw away a reply that was already on its way, which
                # the owner heard as her starting a sentence and vanishing. The log
                # line for it read "device→live ended cleanly, closing session",
                # which sounded like success.
                #
                # So when the input side finishes we let the output side finish
                # too, up to a bounded wait. A reply longer than this is a stuck
                # stream, not a long answer.
                #
                # live→device ending is the opposite: Gemini is done or has failed,
                # and there is nothing left to wait for.
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
                # Name which side ended and why. Without this a silent clean exit on
                # either bridge looked identical to a crash: the only thing in the log
                # was the CancelledError of the OTHER task, which is a symptom, never
                # the cause.
                for t in done:
                    side = "device→live" if t is t_in else "live→device"
                    if t.cancelled():
                        logger.info("[voice_ws] %s cancelled", side)
                    elif t.exception():
                        exc = t.exception()
                        logger.error("[voice_ws] %s failed: %r", side, exc,
                                     exc_info=exc)
                        # A refusal that got past the probe must not be repeated for
                        # the life of the dyno. Unpin, and the next call re-walks.
                        if "CONTENT_TYPE_AUDIO" in str(exc) or "1007" in str(exc):
                            forget_live_model(model_name)
                    else:
                        logger.info("[voice_ws] %s ended cleanly, closing session", side)
            finally:
                # What `async with` would have done. Not suppressing anything: an
                # error in the bridge belongs in the handler below, not swallowed here.
                await cm.__aexit__(None, None, None)

            # Reconnect only when Gemini asked us to, the device is still
            # there, and we hold a handle to come back with. Any other ending
            # is the call being over.
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


async def _device_to_live(reader: "_DeviceReader", session, recent: "_RecentAudio",
                          *, verify: bool = True,
                          live_state: Optional[Dict[str, Any]] = None) -> None:
    """Read PCM frames from the device and stream to Live with manual turn control.

    We run our own VAD: on speech we open an activity, and on about 700ms of
    silence we close it. Before closing we first verify who spoke and inject
    their persona, so Sandy replies with the right personality from the very
    first sentence (owner vs guest).
    """
    from google.genai import types
    import numpy as np

    speaking = False
    silence_ms = 0.0
    utter_ms = 0.0

    frames = 0
    sent = 0
    heard_ms = 0.0
    window: "deque[float]" = deque(maxlen=_VAD_FLOOR_FRAMES)
    threshold = float(_VAD_RMS_FLOOR)
    consumed = 0
    speech_ms = 0.0
    backlog = reader.pending()
    draining = backlog > _BACKLOG_FRAMES
    if draining:
        logger.info("[voice_ws] %d frames were buffered during setup — one turn, "
                    "not several", backlog)

    async def _send_audio(chunk: bytes) -> None:
        """Forward one device frame, split to the size Google asks for.

        **The board sends a hundred and twenty-eight milliseconds at a time;
        the Live API documentation asks for twenty to forty.** A big frame is a
        coarse frame: the earliest the far end can notice speech starting or
        stopping is the boundary of whichever one it is inside, so every turn
        begins and ends late by up to a frame. Splitting costs nothing — it is
        the same bytes, in more messages — and it is the cheapest latency in the
        whole path.
        """
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
        """End the user's turn and tell Gemini so. The one thing that must
        happen for an answer to exist at all.

        **Except while she is already answering.** Every `activity_end` starts a
        generation, and a second one cancels the first — so a cough, a chair, a
        second of room noise between the question and the reply threw the answer
        away. The log said it plainly: turn closed, first response from Gemini,
        turn closed again nine hundred milliseconds later, `replied=0 chars`.
        A real interruption is still honoured; it just has to be long enough to
        be a sentence rather than a noise.
        """
        nonlocal speaking, silence_ms, utter_ms, speech_ms
        # **Measured in speech, not in elapsed time.** `utter_ms` counts every
        # frame while a turn is open, silence included — so the seven hundred
        # milliseconds of quiet that *end* the turn are inside it, and a blip of
        # two frames measured as a second and a half.
        if state.get("replying") and speech_ms < _BARGE_MIN_MS:
            logger.info("[voice_ws] ignoring a %.1fs blip while she is answering",
                        speech_ms / 1000)
            speaking = False
            silence_ms = 0.0
            utter_ms = 0.0
            speech_ms = 0.0
            return
        if verify and utter_ms >= _VAD_MIN_UTTER_MS:
            await _verify_and_inject(session, recent.snapshot())
        await session.send_realtime_input(activity_end=types.ActivityEnd())
        state["replying"] = True
        logger.info("[voice_ws] turn closed after %.1fs of speech (%s)",
                    utter_ms / 1000, reason)
        speaking = False
        silence_ms = 0.0
        utter_ms = 0.0
        speech_ms = 0.0

    # **Pulled with a deadline, not iterated.**
    #
    # The board no longer uploads the room — it sends while somebody is talking
    # and stops when they stop. So the end of a question arrives as *nothing
    # arriving*, and a plain `async for` waits for that forever. The frame is
    # awaited with a timeout instead, and a gap is an answer.
    #
    # The task is never cancelled on timeout: cancelling `__anext__` of an async
    # generator closes the generator, which would end the call at the first pause
    # instead of ending the turn.
    stream = reader.frames().__aiter__()
    frame_task: Optional[asyncio.Task] = None
    # **The pull task never outlives this bridge.**
    #
    # `asyncio.wait` does not cancel what it was given, so a cancel from
    # outside — which is what a GoAway reconnect does to this task — left a
    # pending `__anext__` on the shared queue. The next bridge opened a
    # second reader over the same queue and the orphan, being first in line,
    # ate a frame; worse, it could eat the end-of-stream marker, after which
    # the new bridge never finished and held a worker thread for ten minutes.
    try:
        while True:
            if frame_task is None:
                frame_task = asyncio.ensure_future(stream.__anext__())
            finished_now, _ = await asyncio.wait({frame_task}, timeout=_SILENCE_GAP_S)
            if not finished_now:
                # Nothing for a whole gap. If a turn is open, it is over — and
                # **this is not conditional on the backlog.** It was, which put
                # the one detector built as a safety net behind the very flag it
                # exists to catch. A device that has stopped sending has stopped
                # sending; by definition there is no backlog left to drain.
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

            # **Speech is louder than the room. It is not louder than a constant.**
            #
            # A fixed number cannot be right in two rooms. Set it too high and the
            # gate never opens — Gemini gets silence for the whole call. Set it too
            # low, or stand the robot near a fan, and every frame counts as speech:
            # the silence that ends a turn never accumulates, nobody ever tells
            # Gemini the question is over, and she says nothing at all. That second
            # one is what production did, for a whole day, with a threshold of 350
            # in a room whose floor was above it.
            #
            # So the floor is measured: **the quietest moment in the last few
            # seconds is the room.** Nobody talks continuously, so that minimum is
            # the room and nothing else — and unlike a decaying average it cannot be
            # dragged upward by a long sentence. Speech is what stands above it by a
            # clear margin, with an absolute minimum underneath so a silent room
            # cannot promote a hiss to a sentence.
            # **The floor is learned between sentences, not during them.**
            #
            # Taking the minimum of the last few seconds works only while room
            # frames keep arriving. The board now gates its uplink and sends
            # speech alone, so a window that keeps updating fills with speech,
            # the floor climbs to the quietest *word*, and the threshold sits
            # above the voice: the second question of a call was never forwarded
            # at all, and a long first one closed a dozen times mid-sentence.
            #
            # So the window only takes frames while no turn is open. Inside an
            # utterance the threshold is whatever the room was just before it
            # began, which is the only honest measure of it.
            if not speaking:
                window.append(rms)
                if len(window) >= _VAD_FLOOR_MIN_FRAMES:
                    threshold = max(min(window) * _VAD_FLOOR_FACTOR, _VAD_RMS_FLOOR)
            # **And nothing is speech until the room is known.** Opening a turn
            # on the first frame, before there is anything to compare it to,
            # freezes the threshold at the absolute minimum for the whole
            # utterance — after which the room itself never falls below it and
            # the turn cannot close. Half a second of listening first costs
            # nothing: the board sends its preroll ahead of the first word, and
            # that preroll is the room.
            is_speech = (len(window) >= _VAD_FLOOR_MIN_FRAMES
                         and rms >= threshold)

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
                if is_speech:
                    speech_ms += ms
                silence_ms = 0.0 if is_speech else silence_ms + ms

                # **A backlog is one question, not four.**
                #
                # The robot records from the wake word, and the session behind it
                # takes seconds to open — so speech sits in the buffer and then
                # drains at machine speed, and the pauses inside one sentence look
                # like the ends of four separate questions. Each turn we open cancels
                # the reply to the last: four `turn closed` lines in two seconds and
                # `replied=0 chars` every time.
                #
                # So no turn is closed while frames are still queued. **The queue is
                # the measure, not the clock** — comparing the audio clock to the
                # wall clock said "still catching up" for the entire call, because a
                # device streaming in real time keeps its head start forever, and
                # then nothing ever closed the turn at all.
                # **Once, at the start, and then never again.**
                #
                # Asking "is the queue deep right now" every frame is a test that can
                # stay true forever: a device sending one frame every one hundred and
                # thirty milliseconds keeps a frame or two in flight at all times, so
                # the hold never lifted and a whole call went by with no turn closed
                # — thirty-nine seconds of speech and not one answer. The backlog is
                # a fact about *the beginning* of the call. The moment it is gone, it
                # is gone.
                # **Counted, not sampled.**
                #
                # How deep the queue is *right now* is not the question, and asking
                # it every frame is a test that never comes back false: a device
                # sending one frame every hundred and thirty milliseconds keeps one
                # or two in flight permanently. The question is whether the frames
                # that were already waiting when this call began have gone
                # through.
                #
                # **And it has to be counted against what it counted.**
                # `backlog` is every queued frame, speech or not; `frames`
                # counts only the ones actually *forwarded*, and room audio
                # below the threshold is consumed without being forwarded. One
                # unforwarded frame in the startup queue was enough to leave
                # this set for the rest of the call — and while it is set no
                # turn can close, `speaking` stays true forever, `activity_end`
                # is never sent, and she never answers. That is the outage this
                # whole sequence was trying to end, put back by the fix for it.
                if draining and consumed >= backlog:
                    draining = False
                    if backlog:
                        logger.info("[voice_ws] %d buffered frames are through — "
                                    "live now", backlog)
                if draining:
                    continue

                if silence_ms >= _VAD_SILENCE_MS:
                    # Kept beside the gap test above, deliberately: a board still
                    # running the old firmware uploads the room without pause, so
                    # no gap ever arrives and this is the only thing that would
                    # close a turn. Either detector alone leaves one of the two
                    # boards mute.
                    await _close_turn("quiet frames")
            # Idle silence before any speech: don't forward it, saves bandwidth.
    finally:
        if frame_task is not None:
            frame_task.cancel()

    logger.info("[voice_ws] device→live done: %d frames, %d bytes, "
                "%.1fs audio, %d frames dropped",
                frames, sent, sent / 2 / 16000, reader.dropped)


async def _live_to_device(ws, session, dispatcher, recent: "_RecentAudio",
                          live_state: Optional[Dict[str, Any]] = None) -> None:
    """Read Gemini Live responses, relay audio to the device, handle tool calls.

    `live_state` carries two things back to the caller that decide whether the
    call survives: the latest resumption handle, and whether the server has said
    it is about to hang up.
    """
    if live_state is None:
        live_state = {}
    from google.genai import types


    loop = asyncio.get_event_loop()
    gate_on = _speaker_gate_enabled()

    # One thread, ours, for everything written to the device.
    #
    # Two things were wrong with using the shared default executor here.
    #
    # It was contended: the same pool held the parked reader threads, so every
    # audio chunk queued behind them. Her voice arrived in bursts and gaps, and
    # the more sessions had been left hanging, the worse it got — which is why
    # the choppiness came and went with no pattern anyone could see.
    #
    # And it was not ordered. A pool with several threads gives no guarantee
    # about which write lands first. It happens to work today only because each
    # send is awaited before the next is queued; that is one refactor away from
    # shuffling audio frames, and shuffled audio does not sound broken, it
    # sounds like a bad connection.
    #
    # One worker gives strict FIFO by construction and cannot be starved.
    tx = ThreadPoolExecutor(max_workers=1, thread_name_prefix="voice-tx")

    # وتنفيذ الأدوات كمان بمجمعه.
    #
    # «شغّلي الكشاف» بيروح للوسيط وبيستنى، و«شو الطقس» بيروح للإنترنت. هدول
    # كانوا ع المجمع المشترك، فكل أداة بتنتظر مكان جنب القراءات والإرسال —
    # وأبطأ أداة كانت بتأخّر الصوت اللي بعدها.
    #
    # اتنين مش واحد: ساندي بتقدر تستدعي أداتين بنفس الدور (طفّي الضو وشغّل
    # المروحة)، ووحدة بتصير تستنى التانية بلا سبب.
    tools_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="voice-tool")

    # ── Keeping the socket alive ─────────────────────────────────────────────
    #
    # **Heroku's router closes any connection that carries fewer than about
    # fifty bytes in fifty-five seconds**, and logs it as H15. That is not a
    # setting we can change.
    #
    # A voice session goes quiet all the time and for entirely healthy reasons:
    # the owner is thinking, or the robot is listening and nobody has spoken
    # yet. Nothing flows in either direction, the rolling window runs out, and
    # the router hangs up on a session that was working perfectly.
    #
    # What that looked like from the outside was the worst part. The session
    # died mid-thought, so the reply never came and any tool call in flight —
    # `ask_clarification`, a reminder, the flash — was cut off before it ran.
    # It read as "she ignores me sometimes" and as "the tools do not work", and
    # neither is what happened: **the connection was closed under her.**
    #
    # Twenty seconds is deliberately well inside the window. This costs a
    # handful of bytes a minute and removes a failure that presents as a dozen
    # different bugs.
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
        """Send something small whenever the socket has been quiet too long.

        Only when quiet: during a reply the audio itself keeps the window open,
        and an extra frame in the middle of that is one more thing for the
        device's parser to step around.
        """
        while True:
            await asyncio.sleep(_KEEPALIVE_S / 2)
            if time.monotonic() - _last_send >= _KEEPALIVE_S:
                try:
                    await send_msg({"type": "ping"})
                except Exception:  # noqa: BLE001 — a dead socket ends the session anyway
                    return

    _user_buf: List[str] = []
    _sandy_buf: List[str] = []

    # The other half of the missing evidence. `_first` fires on the very first
    # message of any kind from Gemini — a transcript fragment, an audio part, a
    # tool call — which is the moment that separates "she is slow" from "the
    # sentence never became a turn". `_audio_out` is what actually reached the
    # speaker; a session that heard, thought, and sent nothing looks the same
    # from the board as one that never heard anything.
    _seen = {"any": False, "user_text": False, "audio_out": 0}
    _audio = {"at": time.monotonic(), "chunks": 0, "wait": 0.0,
              "send": 0.0, "worst": 0.0}
    _turn_audio = {"n": 0}

    async def _handle(response) -> bool:
        """Process one Live response; return True to stop the session.

        Speaker identification + persona injection happen in _device_to_live at
        end-of-utterance (manual turn control), so this side just relays audio,
        saves STM, and gates sensitive tools.
        """

        if not _seen["any"]:
            _seen["any"] = True
            logger.info("[voice_ws] first response from Gemini")

        # **The handle, kept every time it changes.** It is what makes the
        # reconnect invisible: the same session, with everything said so far
        # still in it. Without one, a reconnect is a stranger asking who you are.
        update = getattr(response, "session_resumption_update", None)
        if update is not None and getattr(update, "resumable", False):
            handle = getattr(update, "new_handle", "")
            if handle:
                live_state["resume"] = handle

        # And the warning that the connection is ending. Ten minutes is the
        # documented lifetime; this arrives before the end, with the time left.
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
            await send_msg({"type": "interrupted"})

        # Audio plus text response: relay the audio, capture the text.
        if response.server_content and response.server_content.model_turn:
            for part in response.server_content.model_turn.parts:
                if part.inline_data and part.inline_data.data:
                    if not _seen["audio_out"]:
                        logger.info("[voice_ws] first reply audio → device")
                    _seen["audio_out"] += len(part.inline_data.data)
                    _turn_audio["n"] += len(part.inline_data.data)
                    # **Where the stutter comes from, measured rather than
                    # guessed.** The reply arrives as chunks and is played as it
                    # arrives, so a gap anywhere becomes a gap in her voice — and
                    # there are three places it can open: Gemini producing slowly,
                    # this dyno being busy, or the link to the robot. `wait` is
                    # how long we sat with nothing to send; `send` is how long
                    # handing it over took. Their sum against the audio's own
                    # duration says which of the three it is: if the sum exceeds
                    # the audio, the robot runs out before the next piece lands.
                    _now = time.monotonic()
                    _wait = _now - _audio["at"]
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
            await send_msg({"type": "end_turn"})
            # **Concatenated, not space-joined.**
            #
            # Gemini streams a transcript as a run of fragments, and a fragment
            # is not a word — it is whatever part of one was ready. The pieces
            # already carry their own spaces. Putting a space between them adds
            # one inside every word it split:
            #
            #     heard='اه لي ها و خ لي ها  الا ولو يه  بت اعت ها  عاليه'
            #
            # which is "اهليها وخليها الا ولويه بتاعتها عاليه" with the seams
            # showing. Arabic makes it obvious because the letters join; in
            # English it reads as a typo and had been going unnoticed.
            #
            # This is not only a log cosmetic. This text is what gets written to
            # short- and long-term memory, so every voice turn has been stored
            # shredded — and read back to her later as though it were what was
            # said.
            user_text = "".join(_user_buf).strip()
            sandy_text = "".join(_sandy_buf).strip()

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
            # **Characters were the wrong thing to count.**
            #
            # `replied=0 chars` was read for days as "she said nothing", and it
            # does not mean that: the reply is audio, and the text beside it is
            # a transcript that often has not arrived by the time the turn
            # completes. A turn that produced a second of speech and no
            # transcript logged identically to one that produced silence — two
            # completely different faults wearing one line.
            logger.info("[voice_ws] turn done: heard=%r replied=%d chars, "
                        "%d bytes of audio (%.1fs)",
                        user_text[:120], len(sandy_text), _turn_audio["n"],
                        _turn_audio["n"] / 2 / 24000)
            _turn_audio["n"] = 0
            if user_text and sandy_text:
                # مش `await`.
                #
                # هاد كتابة ع قاعدة البيانات، وكان موقوف عليه بنص حلقة الردّ —
                # يعني كل نهاية دور بتوقف بثّ الصوت لحدّ ما تخلص الكتابة. لو
                # القاعدة تأخّرت لحظة، بتسمعها سكتة بآخر كل جملة، وما في إشي
                # ع الشاشة بيربط السكتة بالحفظ.
                #
                # الذاكرة مش ع المسار الحرج: فشلها بيخسّر سطر بالسجل، وتأخيرها
                # ما بيجوز يخسّر مقطع صوت. بنطلقها وبنكمّل.
                loop.run_in_executor(None, _save_voice_turn, user_text, sandy_text,
                                     get_voice_identity(), get_voice_channel())

            _user_buf.clear()
            _sandy_buf.clear()

        # Tool calls: dispatch them and return the result to Live.
        if response.tool_call and dispatcher:
            fn_responses: List[types.FunctionResponse] = []
            for fc in response.tool_call.function_calls:
                # V4.4–V4.5: أمر حسّاس + البوابة مفعّلة → تأكّد إنه صوت المالك أولاً.
                if gate_on and fc.name in _SENSITIVE_TOOLS:
                    verified = await loop.run_in_executor(
                        None, _verify_owner, recent.snapshot(), get_voice_identity()
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
                # No spoken confirmation step. Owner's decision, and it was the
                # right one.
                #
                # Every gated call cost a full extra round trip — the model had
                # to ask, wait for an answer, and call again — so a sentence that
                # should light a lamp in under a second took several and ended in
                # "are you sure?". For an assistant you talk to, that is the
                # difference between a device and a nuisance.
                #
                # Most of what was gated was never destructive anyway; that list
                # has been cut back to real, irreversible data loss (see
                # agent/guards.py). Deletes now happen when asked, immediately.
                # The speaker gate above still stands where it is enabled: it
                # answers "is this the owner", which is a different question and
                # the one actually worth asking.
                # الهوية بتسافر مع الأداة. الأدوات بتكتب بقاعدة البيانات، والكتابة
                # مقيّدة بالحساب — فأداة بتشتغل بلا هوية بتكتب لحساب غلط أو
                # بتفشل بصمت، وساندي بتقول «تمام عملتها».
                result = await loop.run_in_executor(
                    tools_pool, _dispatch_tool, dispatcher, fc.name,
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

    # session.receive() yields one turn then ends, so we loop to keep the
    # conversation going across turns (the session itself stays open). We exit
    # on go_away, an error, or the device closing.
    #
    # try/finally, not a bare loop: this task gets cancelled whenever the other
    # side finishes first, and a cancelled task still has to give its thread
    # back. A pool leaked once per session is the same failure this file was
    # just rewritten to remove — one thread each, quietly, until the worker runs
    # out and the robot stops being answered.
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
                    # 24 kHz, 16-bit: two bytes a sample. If `audio` is less
                    # than `wait`, she is being played faster than she is
                    # arriving, and that is exactly what a listener hears as a
                    # bad line.
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
