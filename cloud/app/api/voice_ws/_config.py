"""Shared constants, logger and env-tunables for the voice_ws package."""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_HMAC_KEY: bytes = os.environ.get("SANDY_WS_HMAC_KEY", "").encode()
_LEGACY_SECRET: str = os.environ.get("ROBOT_WS_SECRET", "")          # backward compat
# **The Live model, and why this is a list.**
#
# `gemini-2.5-flash-native-audio-latest` was the configured default and the
# service refused every session with
#
#     1007 — The audio content type (CONTENT_TYPE_AUDIO) is not supported
#            for this model configuration.
#
# — the handshake succeeded, the memory seed went out, and the first audio frame
# closed the socket. Nothing in this repo was wrong; the alias no longer names a
# model that accepts audio input on the Live API, and Google renames these
# faster than a deploy cycle.
#
# So the session tries these in order and keeps the first that connects, for the
# life of the process (`_config.live_model()`). A pinned name that goes stale
# takes voice down completely and silently; a list degrades to "the newest one
# that still works" and says in the log which that was.
#
# `SANDY_LIVE_MODEL` still wins outright when set — that is the escape hatch for
# a name this list has not learned yet, and it needs no deploy.
_LIVE_MODEL_CANDIDATES: tuple[str, ...] = (
    "gemini-live-2.5-flash-preview",
    "gemini-2.5-flash-preview-native-audio-dialog",
    "gemini-2.0-flash-live-001",
)
_LIVE_MODEL: str = os.environ.get("SANDY_LIVE_MODEL", "")

_live_model_working: str = ""


def live_model_candidates() -> tuple[str, ...]:
    """What to try, in order. An explicit env var is the only entry when set."""
    if _LIVE_MODEL:
        return (_LIVE_MODEL,)
    if _live_model_working:
        return (_live_model_working,) + tuple(
            m for m in _LIVE_MODEL_CANDIDATES if m != _live_model_working)
    return _LIVE_MODEL_CANDIDATES


def remember_live_model(name: str) -> None:
    """Pin the one that connected, so later sessions do not re-walk the list."""
    global _live_model_working
    if name and name != _live_model_working:
        _live_model_working = name
        logger.info("[voice_ws] live model settled on %s", name)
_ANTI_REPLAY_MS: int = 30_000

# Phase 4 (V4.4–V4.6): على المايك (اللابتوب) نتأكد إنه صوت المالك قبل أمر حسّاس.
# على التلي/الموقع الهوية معروفة، فالتحقّق هون فقط. مفعّل بـ SANDY_REQUIRE_SPEAKER_AUTH=1.
_SENSITIVE_TOOLS = {
    "task_delete", "reminder_delete", "calendar_delete",
    "schedule_message_to_self",
}
# نحتفظ بآخر ~5 ثوانٍ من صوت الجهاز (16kHz·16bit·mono = 32KB/s) للتحقّق عند أمر حسّاس.
_RECENT_AUDIO_MAX_BYTES = 160_000
# أقل صوت كافٍ لتحقّق موثوق ≈ 0.5s (16kHz·16bit = 32KB/s → 16KB).
_MIN_VERIFY_BYTES = 16_000

# كشف الكلام عندنا (VAD) — نتحكّم بنهاية الدور عشان نتحقّق من الصوت قبل ما تردّ ساندي.
_VAD_RMS_THRESHOLD = float(os.getenv("SANDY_VAD_RMS", "350"))      # فوقها = كلام
_VAD_SILENCE_MS = int(os.getenv("SANDY_VAD_SILENCE_MS", "700"))    # صمت ينهي الدور
_VAD_MIN_UTTER_MS = int(os.getenv("SANDY_VAD_MIN_MS", "300"))      # أقصر من هيك = نتجاهله
_VOICE_CTX_TTL_S = float(os.getenv("SANDY_VOICE_CTX_TTL_S", "60"))
