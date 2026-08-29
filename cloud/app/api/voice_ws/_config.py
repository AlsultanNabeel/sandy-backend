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
# `SANDY_LIVE_MODEL` goes **first**, and does not exclude the rest. It used to be
# the only entry when set, which turned the escape hatch into a trap: the config
# var held `gemini-2.5-flash-native-audio-latest`, that name refuses audio input,
# and because it was the whole list there was nothing to fall through to. Voice
# was down with the fallback logic sitting right there, disabled by a setting
# whose purpose was to help.
# **These are the names the service itself reported**, on 2026-08-29, filtered
# to the ones that take audio in and give audio back. The three that were here
# before were all dead — every session spent about a second and a half failing
# through them before discovery found a live one, and printed three warnings
# doing it.
#
# Left out on purpose, from the same listing:
#   gemini-3.5-transcribe-live        refuses the AUDIO response modality
#   gemini-3.5-live-translate-preview a translator, not a conversation
#   gemini-robotics-er-2-streaming    a different product entirely
#
# When these go stale too — and they will — `_discover_live_models` asks the API
# and the log names what it found. This list is the fast path, not the truth.
_LIVE_MODEL_CANDIDATES: tuple[str, ...] = (
    "gemini-2.5-flash-native-audio-latest",
    "gemini-2.5-flash-native-audio-preview-12-2025",
    "gemini-2.5-flash-native-audio-preview-09-2025",
    "gemini-3.1-flash-live-preview",
)
_LIVE_MODEL: str = os.environ.get("SANDY_LIVE_MODEL", "")

_live_model_working: str = ""


def live_model_candidates() -> tuple[str, ...]:
    """What to try, in order: the preferred one first, then everything else.

    Preference is the env var if set, otherwise whichever name last worked in
    this process. Neither one removes the others from the list — a preference
    that stops working has to be survivable, or it is a single point of failure
    wearing the clothes of a convenience.
    """
    order: list[str] = []
    for name in (_LIVE_MODEL, _live_model_working, *_LIVE_MODEL_CANDIDATES):
        if name and name not in order:
            order.append(name)
    return tuple(order)


def remember_live_model(name: str) -> None:
    """Pin the one that worked, so later sessions do not re-walk the list."""
    global _live_model_working
    if name and name != _live_model_working:
        _live_model_working = name
        logger.info("[voice_ws] live model settled on %s", name)


def pinned_live_model() -> str:
    """The model a real session has already proved, if any."""
    return _live_model_working


def forget_live_model(name: str) -> None:
    """Unpin a model that has just failed in a live session.

    The probe cannot catch everything, and a name that worked yesterday can stop
    working today. Without this, one bad answer would be repeated for the life
    of the dyno, because the failing model stays the preferred one.
    """
    global _live_model_working
    if name and name == _live_model_working:
        _live_model_working = ""
        logger.warning("[voice_ws] live model %s failed in session — unpinned", name)
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
# بعد هالمدة من صوت واصل بلا ولا كلمة انكشفت، العتبة غلط مش الغرفة — بتنزل لمرة.
# ثابت، مش متغيّر بيئة: هاي شبكة أمان لعتبة موجودة أصلاً، ومفتاح تعيير إلها
# بيعني مفتاحين لنفس القرار.
_VAD_BLIND_MS = 4000
_VOICE_CTX_TTL_S = float(os.getenv("SANDY_VOICE_CTX_TTL_S", "60"))
