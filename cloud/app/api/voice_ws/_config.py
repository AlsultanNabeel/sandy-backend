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
# القراءة من القاعدة بتصير مرّة بعمر العمليّة، مش كل مكالمة.
_live_model_loaded: bool = False
_LIVE_MODEL_COLL = "sandy_runtime"
_LIVE_MODEL_ID = "live_model"


def _load_pinned_live_model() -> None:
    """آخر موديل اشتغل فعليًّا — من القاعدة، مرّة وحدة.

    **التثبيت بالذاكرة بيموت مع العمليّة.** هيروكو بيشغّل عاملين وبيعيد تشغيلهم
    كل يوم، فكل عامل جديد بيرجع يمشي عالقائمة من أوّلها — ولمّا تبوظ الأسماء
    الأولى (وهاد صار: أربعة أسماء ماتوا مع بعض)، كل مكالمة بتدفع ثانية ونص
    محاولات فاشلة وتلات تحذيرات، لكل عامل، كل يوم. اللي تعلّمناه لازم يعيش
    أطول من العمليّة اللي تعلّمته.
    """
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
    except Exception as exc:  # noqa: BLE001 — تفضيل، مش شرط
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
    """What to try, in order: the preferred one first, then everything else.

    Preference is the env var if set, otherwise whichever name last worked in
    this process. Neither one removes the others from the list — a preference
    that stops working has to be survivable, or it is a single point of failure
    wearing the clothes of a convenience.
    """
    _load_pinned_live_model()
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
        # بالخلفية: المكالمة صارت مفتوحة وصاحبها بيستنّى، وهاي كتابة للي بعده.
        try:
            from app.utils.thread_pool import submit_background

            submit_background(_persist_live_model, name, _label="live-model-pin")
        except Exception:  # noqa: BLE001
            logger.debug("[voice_ws] pinned model not saved", exc_info=True)


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
        # وبتنشال من القاعدة كمان، وإلا كل عامل جديد بيرجع يثبّتها.
        try:
            from app.utils.thread_pool import submit_background

            submit_background(_persist_live_model, "", _label="live-model-unpin")
        except Exception:  # noqa: BLE001
            logger.debug("[voice_ws] unpin not saved", exc_info=True)


def _reset_live_model_cache() -> None:
    """للاختبارات: خلّي القراءة من القاعدة تصير من جديد."""
    global _live_model_working, _live_model_loaded
    _live_model_working = ""
    _live_model_loaded = False
_ANTI_REPLAY_MS: int = 30_000

# Phase 4 (V4.4–V4.6): على المايك (اللابتوب) نتأكد إنه صوت المالك قبل أمر حسّاس.
# على التلي/الموقع الهوية معروفة، فالتحقّق هون فقط. مفعّل بـ SANDY_REQUIRE_SPEAKER_AUTH=1.
_SENSITIVE_TOOLS = {
    "task_delete", "reminder_delete",
    "schedule_message_to_self",
}
# نحتفظ بآخر ~5 ثوانٍ من صوت الجهاز (16kHz·16bit·mono = 32KB/s) للتحقّق عند أمر حسّاس.
_RECENT_AUDIO_MAX_BYTES = 160_000
# أقل صوت كافٍ لتحقّق موثوق ≈ 0.5s (16kHz·16bit = 32KB/s → 16KB).
_MIN_VERIFY_BYTES = 16_000

# كشف الكلام عندنا (VAD) — نتحكّم بنهاية الدور عشان نتحقّق من الصوت قبل ما تردّ ساندي.
# **الكلام أعلى من الغرفة، مش أعلى من رقم.**
#
# رقم ثابت ما بيزبط بغرفتين. عالي كتير: البوابة ما بتفتح وجيميناي بيوصله صمت.
# واطي كتير أو في مروحة: كل إطار بيصير كلام، والصمت اللي بينهي الدور ما
# بيتجمّع أبداً، وما حدا بيقول لجيميناي إنّ السؤال خلص — وهاي اللي صارت.
#
# فالأرضية بتنقاس: بتنزل فوراً لأي لحظة أهدى وبترجع تطلع ببطء — هيك بتتصرّف
# الغرفة. والكلام هو اللي بيعلى عنها بفرق واضح، مع حد أدنى مطلق عشان غرفة
# ساكتة ما تخلّي حفيف ضجّة جملة.
_VAD_FLOOR_FACTOR = 2.5
_VAD_RMS_FLOOR = 120.0
# نافذة الأرضية: أهدأ لحظة خلال آخر تلات ثواني. ومنستنى شوية إطارات قبل ما
# نصدّقها — قبلها منستعمل الحد الأدنى.
#
# **بالوقت، مش بعدد الإطارات.** كانت أربعة وعشرين إطارًا، وهاد رقم صحيح للوح
# لحاله: إطاره مية وتمانية وعشرين جزء من الألف، يعني تلات ثواني، وبهالمدة
# أكيد في شهقة أو سكتة بتكون هي الغرفة. التطبيق بيبعت إطارًا كل أربعين جزء
# تقريبًا، فنفس الأربعة وعشرين صاروا **ثانية وحدة** — وثانية من نصّ جملة ما
# فيها ولا سكتة، فأهدأ لحظة فيها هي أهدأ **كلمة**، والعتبة بتطلع فوق الصوت
# وبتضلّ فوقه. النتيجة بالسجل: مكالمة واحد وتلاتين ثانية، الإطارات واصلة،
# و«من الجهاز للبث: صفر إطار» — البوابة ما فتحت ولا مرّة.
_VAD_FLOOR_MS = 3000.0
_VAD_FLOOR_MIN_FRAMES = 4
# نافذة تانية أطول، بتشتغل شبكة أمان: لو ضلّينا نسمع صوت ولا فتحت البوابة ولا
# مرّة لهالمدة، معناها العتبة غلط — فمنرجع نحسبها من أهدأ لحظة بنص دقيقة، وهاي
# بأي مكالمة حقيقية بتكون الغرفة. أحسن من الرجوع للحد الأدنى المطلق، لأنّ غرفة
# فيها مروحة بيخلّي البوابة مفتوحة ع طول والدور ما بينتهي — نفس الصمت، سبب تاني.
_VAD_ROOM_MS = 30000.0
_VAD_STUCK_MS = 3000.0
# سقف لتقدير الغرفة **قبل ما تفتح البوابة ولا مرّة**.
#
# أول ثانية بالمكالمة هي أخطر لحظة للتقدير: اللي بالطابور وقت ما بلّشنا ممكن
# يكون صوت صاحبه نفسه — بيحكي وهو لسا بيفتح المكالمة — فأهدأ إطار موجود هو
# أهدأ **كلمة**، والعتبة بتنبني فوق صوته وما بتفتح أبدًا. وغرفة ساكنة شدّتها
# نادرًا بتعدّي هالرقم، فالسقف بيمنع الخطأ هاد وبس. بعد ما تفتح البوابة مرّة،
# صار عنا قياس حقيقي للغرفة بين الجُمَل، والسقف بيرتفع.
_VAD_ROOM_MAX = 600.0
# سقف لطول الدور الواحد. لو صار التقدير واطي كتير، كل إطار بيصير كلام، والصمت
# اللي بينهي الدور ما بيتجمّع أبدًا — والتطبيق ما بيوقف الإرسال، فحتى الفجوة ما
# بتجي. ربع دقيقة كلام متواصل معناها في خلل، مش سؤال.
_VAD_MAX_UTTER_MS = 15000.0

# حجم القطعة اللي بتنبعت لجيميناي. توثيقهم بيطلب من عشرين لأربعين جزء من الألف؛
# اللوح بيبعت مية وتمانية وعشرين. أربعين × ستاشر ألف عيّنة × بايتين = ١٢٨٠ بايت.
_CHUNK_BYTES = 1280


# حدود الجلسة من توثيق جوجل: الصوت بيتجمّع حوالي خمسة وعشرين رمز بالثانية،
# فبنضغط عند خمسة وعشرين ألف وبنخلّي نافذة تمن آلاف. بدونها الجلسة بتموت عند
# ربع ساعة، والاتصال نفسه عمره حوالي عشر دقايق.
_COMPRESS_TRIGGER_TOKENS = 25_000
_COMPRESS_WINDOW_TOKENS = 8_000
# صمت ينهي الدور. سبعمية كانت قصيرة: وقفة تفكير بنصّ جملة بتعدّيها، فبتوصل
# جيميناي نص السؤال وبتردّ قبل ما يخلص. وتطويلها لحالها بيأخّر كل ردّ —
# فمعها `_still_the_same_sentence`، اللي بيرجّع الدور لو كمّل بعد الإقفال
# وقبل ما تكون قالت إشي.
_VAD_SILENCE_MS = int(os.getenv("SANDY_VAD_SILENCE_MS", "900"))
_VAD_MIN_UTTER_MS = int(os.getenv("SANDY_VAD_MIN_MS", "300"))      # أقصر من هيك = نتجاهله
# اللوح صار يوقف الإرسال لمّا حدا يبطّل يحكي، فنهاية السؤال بتوصل **كلا-وصول**.
# نفس مدة الصمت: فجوة بهالطول معناها الدور خلص.
_SILENCE_GAP_S = _VAD_SILENCE_MS / 1000.0
# قدّيش لازم يحكي عشان نعتبرها مقاطعة حقيقية وهي عم تردّ. أقصر من هيك بيصير
# ضجّة، وكل «نهاية دور» بتلغي الردّ اللي قبلها.
_BARGE_MIN_MS = 1200
# ونفس الحدّ، بس لمّا تكون لسا ما قالت ولا كلمة من وقت ما سكّر الدور: هون اللي
# بيتلغي توليد ما طلع منه صوت، فالكلفة أخفّ، والحالة الشائعة هي إنه بيكمّل
# جملته. شوف `_barge_bar_ms`.
_CONTINUE_MIN_MS = 800
# سقف للكلام المحجوز قبل ما نقرّر إنها مقاطعة — ثانيتين، كفاية للجملة اللي بدها
# تقاطع، وما بتخلّي الذاكرة تكبر لو الغرفة ضجّة متواصلة.
#
# **بالوقت، مش بعدد الإطارات** — نفس الخلل يلّي كان بنافذة الأرضية، ومكان تاني.
# ستّاشر إطار من اللوح تنتين ثانية؛ ستّاشر إطار من التطبيق **ستّمية وأربعين جزء
# من الألف** — أقصر من حدّ المقاطعة نفسه. يعني الإطارات المحجوزة ما كانت تكفي
# تعدّي الحدّ ولا مرّة، وبأي طول حكي: المقاطعة من التطبيق كانت مستحيلة حسابيًّا،
# حتى لو المايك كان مفتوح.
_HELD_MS_MAX = 2000.0
# كم إطار مسموح يكون بالطابور ولسا منعتبر إنّا حيّ. بثّ بالوقت الحقيقي بيخلّي
# الطابور صفر أو واحد؛ أكتر من هيك معناها في كلام مخزون لسا ما مرّ.
_BACKLOG_FRAMES = 2
# **مين بيقرّر إنك خلصت حكي، بمكالمة التطبيق.**
#
# كاشفنا بيقيس **الشدّة**: الصوت أعلى من الغرفة = كلام، وتسعمية جزء من الألف
# تحتها = خلص. وهاد بالضبط اللي بيقطعك: وقفة تفكير بنصّ جملة ما بتفرق عنده عن
# آخر الجملة، لأنه ما بيسمع **كلام**، بيسمع **صوت**.
#
# جيميناي نفسه عنده كاشف مبني ع نموذج، وهو اللي شغّال بتطبيق جيميناي — والوقفات
# هناك ما بتقطع السؤال، لأنه مصمّم للحوار. وكمان هو اللي بيقرّر المقاطعة وبيبعت
# «انقطع»، فالمقاطعة بتصير زي عندهم بالضبط بدل ما نعيد اختراعها.
#
# ليش كان مطفّى: **الروبوت**، مش التطبيق. اللوح القديم كان يبثّ الغرفة بلا
# توقّف، وكاشف جيميناي ما لقى صمتًا يعتبره نهاية. فالروبوت بيضلّ عكاشفنا، وهاد
# للتطبيق بس. والحساسية «واطية» بالطرفين: بطيء يعتبر ضجّة بداية كلام، وبطيء
# يعتبر وقفة نهاية كلام — العكس تمامًا من اللي كان بيزعجك.
#
# **وجرّبناه، وما زبط — فرجع الافتراضي لكاشفنا.** أول مكالمة حقيقية عليه:
# اثنين وعشرين ثانية حكي قبل ما يعتبر إنه في دور أصلاً، وبعد الدور الوحيد
# أربعين ثانية حكي عالي (أعلى إطار ستة آلاف ومية) وما ردّ ولا مرّة. والتفريغ
# طلع «Bra, hết.» و«Hi, how are you?» لكلام عربي — يعني كان بيلقط فتافيت من
# الجمل. كاشفنا بالمكالمات اللي قبل ردّ كل مرّة، وتفريغه عربي صحيح.
#
# `SANDY_APP_TURNS=gemini` بيرجّع التجربة بلا بناء تطبيق.
_APP_TURNS_BY_GEMINI: bool = os.getenv("SANDY_APP_TURNS", "ours").strip().lower() == "gemini"
# **والمايك المفتوح قرار لحاله، مش جزء من اللي فوق.** هو اللي بيخلّي المقاطعة
# ممكنة، وبيشتغل مع كاشفنا: حدّ المقاطعة وحجز الإطارات هون من الأول، وكانوا
# بس ما بيوصلهم صوت وهي بتحكي. السيرفر بيقولو للتطبيق بالمصافحة، فالتراجع
# (`SANDY_APP_DUPLEX=0`) كمان من إعدادات هيروكو بلا بناء.
_APP_DUPLEX: bool = os.getenv("SANDY_APP_DUPLEX", "1").strip().lower() not in {"0", "false", "off", "no"}
_APP_SILENCE_MS = 900
_APP_PREFIX_MS = 300

_VOICE_CTX_TTL_S = float(os.getenv("SANDY_VOICE_CTX_TTL_S", "60"))
