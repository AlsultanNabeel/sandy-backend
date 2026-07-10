"""Shared constants, logger and env-tunables for the voice_ws package."""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_HMAC_KEY: bytes = os.environ.get("SANDY_WS_HMAC_KEY", "").encode()
_LEGACY_SECRET: str = os.environ.get("ROBOT_WS_SECRET", "")          # backward compat
_LIVE_MODEL: str = os.environ.get("SANDY_LIVE_MODEL", "gemini-2.5-flash-native-audio-latest")
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
