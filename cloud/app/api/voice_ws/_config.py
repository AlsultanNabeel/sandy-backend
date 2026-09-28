"""Shared constants, logger and env-tunables for the voice_ws package."""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_HMAC_KEY: bytes = os.environ.get("SANDY_WS_HMAC_KEY", "").encode()
_LEGACY_SECRET: str = os.environ.get("ROBOT_WS_SECRET", "")
# Live model candidates, tried in order; the first that connects is pinned (and
# persisted) so later sessions skip dead names. SANDY_LIVE_MODEL goes first but
# never excludes the rest: Google renames these faster than a deploy cycle, and
# _discover_live_models asks the API when all of these are stale.
_LIVE_MODEL_CANDIDATES: tuple[str, ...] = (
    "gemini-2.5-flash-native-audio-latest",
    "gemini-2.5-flash-native-audio-preview-12-2025",
    "gemini-2.5-flash-native-audio-preview-09-2025",
    "gemini-3.1-flash-live-preview",
)
_LIVE_MODEL: str = os.environ.get("SANDY_LIVE_MODEL", "")

_live_model_working: str = ""
# تثبيت آخر موديل اشتغل بيعيش بالقاعدة؛ بينقرا مرّة بعمر العمليّة.
_live_model_loaded: bool = False
_LIVE_MODEL_COLL = "sandy_runtime"
_LIVE_MODEL_ID = "live_model"


def _load_pinned_live_model() -> None:
    """آخر موديل اشتغل فعليًّا — من القاعدة، مرّة وحدة (العمّال بيتعاد تشغيلهم كل يوم)."""
    global _live_model_working, _live_model_loaded
    if _live_model_loaded:
        return
    _live_model_loaded = True
    try:
        from app.db import get_db

        db = get_db()
        if db is None:
            return
        doc = db[_LIVE_MODEL_COLL].find_one({"_id": _LIVE_MODEL_ID}, {"name": 1})
        name = str((doc or {}).get("name") or "").strip()
        if name and not _live_model_working:
            _live_model_working = name
            logger.info("[voice_ws] last working live model was %s", name)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[voice_ws] pinned model read skipped: %s", exc)


def _persist_live_model(name: str) -> None:
    from datetime import datetime, timezone

    try:
        from app.db import get_db

        db = get_db()
        if db is None:
            return
        db[_LIVE_MODEL_COLL].update_one(
            {"_id": _LIVE_MODEL_ID},
            {"$set": {"name": name, "at": datetime.now(timezone.utc)}},
            upsert=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("[voice_ws] pinned model write skipped: %s", exc)


def live_model_candidates() -> tuple[str, ...]:
    """Preferred model (env var, else last working) first, then every other candidate."""
    _load_pinned_live_model()
    order: list[str] = []
    for name in (_LIVE_MODEL, _live_model_working, *_LIVE_MODEL_CANDIDATES):
        if name and name not in order:
            order.append(name)
    return tuple(order)


def remember_live_model(name: str) -> None:
    """Pin the model that worked."""
    global _live_model_working
    if name and name != _live_model_working:
        _live_model_working = name
        logger.info("[voice_ws] live model settled on %s", name)
        # بالخلفية: المكالمة مفتوحة وصاحبها بيستنّى.
        try:
            from app.utils.thread_pool import submit_background

            submit_background(_persist_live_model, name, _label="live-model-pin")
        except Exception:  # noqa: BLE001
            logger.debug("[voice_ws] pinned model not saved", exc_info=True)


def pinned_live_model() -> str:
    """The model a real session has already proved, if any."""
    return _live_model_working


def forget_live_model(name: str) -> None:
    """Unpin a model that just failed in a live session, so it isn't retried for the dyno's life."""
    global _live_model_working
    if name and name == _live_model_working:
        _live_model_working = ""
        logger.warning("[voice_ws] live model %s failed in session — unpinned", name)
        # وبتنشال من القاعدة كمان.
        try:
            from app.utils.thread_pool import submit_background

            submit_background(_persist_live_model, "", _label="live-model-unpin")
        except Exception:  # noqa: BLE001
            logger.debug("[voice_ws] unpin not saved", exc_info=True)


def _reset_live_model_cache() -> None:
    """للاختبارات."""
    global _live_model_working, _live_model_loaded
    _live_model_working = ""
    _live_model_loaded = False


_ANTI_REPLAY_MS: int = 30_000

# على المايك نتأكد إنه صوت المالك قبل أمر حسّاس (SANDY_REQUIRE_SPEAKER_AUTH=1).
_SENSITIVE_TOOLS = {
    "task_delete", "reminder_delete",
    "schedule_message_to_self",
}
# آخر ~5 ثوانٍ من صوت الجهاز (16kHz·16bit·mono = 32KB/s) للتحقّق عند أمر حسّاس.
_RECENT_AUDIO_MAX_BYTES = 160_000
# أقل صوت لتحقّق موثوق ≈ 0.5s.
_MIN_VERIFY_BYTES = 16_000

# VAD عندنا بيحدّد نهاية الدور. العتبة نسبة فوق أرضية الغرفة المقاسة (بتنزل
# فوراً للحظة أهدى وبتطلع ببطء)، مع حد أدنى مطلق.
_VAD_FLOOR_FACTOR = 2.5
_VAD_RMS_FLOOR = 120.0
# أرضية الغرفة: أهدأ لحظة بآخر تلات ثواني — بالوقت مش بعدد الإطارات، لأنّ
# إطار التطبيق 40ms وإطار اللوح 128ms.
_VAD_FLOOR_MS = 3000.0
_VAD_FLOOR_MIN_FRAMES = 4
# شبكة أمان: لو ما فتحت البوابة لهالمدة مع وجود صوت، العتبة غلط؛ منعيد الحساب من أهدأ لحظة بنص دقيقة.
_VAD_ROOM_MS = 30000.0
_VAD_STUCK_MS = 3000.0
# سقف تقدير الغرفة قبل أول فتح للبوابة: أول ثانية ممكن تكون صوت صاحبها نفسه.
_VAD_ROOM_MAX = 600.0
# سقف طول الدور الواحد: ربع دقيقة كلام متواصل معناها خلل.
_VAD_MAX_UTTER_MS = 15000.0

# توثيق جيميناي بيطلب قطع 20–40ms: 40ms × 16kHz × 2 بايت = 1280.
_CHUNK_BYTES = 1280


# ضغط سياق الجلسة (وإلا بتموت عند ربع ساعة).
_COMPRESS_TRIGGER_TOKENS = 25_000
_COMPRESS_WINDOW_TOKENS = 8_000
# صمت ينهي الدور (مع `_still_the_same_sentence` اللي بيرجّع الدور لو كمّل جملته).
_VAD_SILENCE_MS = int(os.getenv("SANDY_VAD_SILENCE_MS", "900"))
_VAD_MIN_UTTER_MS = int(os.getenv("SANDY_VAD_MIN_MS", "300"))      # أقصر = نتجاهله
# اللوح بيوقف الإرسال لمّا يسكت؛ فجوة بطول الصمت معناها الدور خلص.
_SILENCE_GAP_S = _VAD_SILENCE_MS / 1000.0
# أقل كلام يعتبر مقاطعة وهي عم تردّ (أقصر = ضجّة).
_BARGE_MIN_MS = 1200
# نفس الحدّ لمّا ما قالت ولا كلمة بعد إقفال الدور (غالبًا بيكمّل جملته). شوف `_barge_bar_ms`.
_CONTINUE_MIN_MS = 800
# سقف الكلام المحجوز قبل قرار المقاطعة — بالوقت، مش بعدد الإطارات.
_HELD_MS_MAX = 2000.0
# أكتر من هيك بالطابور معناها في كلام مخزون لسا ما مرّ.
_BACKLOG_FRAMES = 2
# مين بيقرّر نهاية الدور بمكالمة التطبيق: كاشفنا افتراضيًا. كاشف جيميناي
# (SANDY_APP_TURNS=gemini) انجرّب وما زبط (تأخير وتفريغ غلط للعربي).
_APP_TURNS_BY_GEMINI: bool = os.getenv("SANDY_APP_TURNS", "ours").strip().lower() == "gemini"
# المايك المفتوح بالتطبيق (بيخلّي المقاطعة ممكنة)؛ SANDY_APP_DUPLEX=0 للتراجع.
_APP_DUPLEX: bool = os.getenv("SANDY_APP_DUPLEX", "1").strip().lower() not in {"0", "false", "off", "no"}
_APP_SILENCE_MS = 900
_APP_PREFIX_MS = 300

_VOICE_CTX_TTL_S = float(os.getenv("SANDY_VOICE_CTX_TTL_S", "60"))
