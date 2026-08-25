"""voice_ws memory."""
from __future__ import annotations
import logging

import contextvars
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional
from app.api.voice_ws._config import (
    logger,
    _VOICE_CTX_TTL_S,
)

# chat_id -> (built_at, text). **Bounded.** A plain dict here grows one entry
# per customer who has ever used voice and never sheds one: the TTL below makes
# a stale entry unused, not gone. Oldest-first eviction, same shape as the
# persona cache in `context_builder`.
_VOICE_CTX_MAX = 128
_voice_ctx_cache: "OrderedDict[str, tuple[float, str]]" = OrderedDict()

# أي جسم بيحكي — الروبوت اللي بالغرفة ولا مكالمة التطبيق.
#
# التنين بيدخلوا من نفس المقبس وبيشاركوا نفس الذاكرة، وهاد صح. بس المالك بيسأل
# «إيمتى قلتلك؟»، والفرق بين «حكيتيلي وإنتي واقفة قدّامي» و«حكيتيلي بالمكالمة»
# فرق حقيقي عنده — زي ما أي حدا بيتذكّر إذا الكلام صار وجهًا لوجه ولا ع الهاتف.
#
# **متغيّرات سياق، مش ذاكرة خيط.**
#
# كانت `threading.local`، والنتيجة إنّ الهوية بتنحفظ ع خيط المصافحة وما حدا
# بيشوفها: `run_in_executor` بيشغّل الدوال ع خيوط تانية. والسجل قال القصّة
# بسطرين متلاصقين — `auth OK owner=1f69b997…` وبعده مباشرة
# `unidentified session`. يعني الهوية انحلّت صح، وانحفظت بمكان اللي بيحتاجها
# ما بيوصله.
#
# ومتغيّر عام كان بيصير أسوأ من الاتنين: جلستين بنفس اللحظة بيدهسوا بعض، وواحد
# بياخد ذاكرة التاني. متغيّر السياق بينسخ لكل مهمة غير متزامنة لحالها.
#
# وبيضلّ ما بيعبر لخيوط المجمّع — عشان هيك اللي بيشتغل هناك بياخد الهوية
# **كوسيط صريح** بدل ما يدوّر عليها.
_identity: contextvars.ContextVar[str] = contextvars.ContextVar(
    "sandy_voice_user", default="")
_channel_name: contextvars.ContextVar[str] = contextvars.ContextVar(
    "sandy_voice_channel", default="")
# Resolved once per session so nothing on the audio path pays a Mongo read.
_speaker_name: contextvars.ContextVar[str] = contextvars.ContextVar(
    "sandy_voice_speaker_name", default="")


def set_voice_channel(name: str) -> None:
    _channel_name.set(name or "")


def get_voice_channel() -> str:
    return _channel_name.get() or "الصوت"


def set_voice_identity(user_id: str) -> None:
    """مين بيحكي بهالجلسة.

    **دالة وحدة، ومتغيّر واحد** — بتنادى عند المصافحة، وبتنادى تاني بأول كل
    دالة بتشتغل ع خيط مجمّع (الوسيط جايي معها). كان في تنين: وحدة للجلسة
    ووحدة «تجاوز» للمجمّع، ومعلومة وحدة بمكانين بتفترق يومًا ما.
    خيط المجمّع بيبلّش بسياق نظيف، فالكتابة عليه ما بتلمس الجلسة.


    قبل هيك كانت الذاكرة الصوتية بتنادي «المالك» من متغيّر بيئة: حساب واحد
    ثابت لكل جلسة صوت بالنظام. اشتغل لأنه كان في شخص واحد. وأول ما صار في
    تسجيل دخول بأبل وجوجل، صار معناها إنّ **كل زبون بيحكي مع ذاكرة زبون تاني**
    — وهاد مش خلل واجهة، هاد تسريب.
    """
    _identity.set((user_id or "").strip())
    _speaker_name.set("")   # re-resolved lazily — see voice_speaker_label


def get_voice_identity() -> str:
    return _identity.get() or ""


def voice_speaker_label() -> str:
    """The session owner's display name, resolved **once** per session.

    `_speaker_directive` runs at the end of every utterance, awaited directly on
    the event loop that is relaying audio — the same loop `_verify_owner` is
    pushed off with `run_in_executor`, and `_save_voice_turn` is pushed off with
    a comment about the pause being audible. A synchronous `find_one` there is
    one stall per sentence, so the lookup happens once and everything after it
    reads a context variable.
    """
    cached = _speaker_name.get()
    if cached:
        return cached
    from app.utils.user_profiles import speaker_label

    name = speaker_label(get_voice_identity() or None)
    _speaker_name.set(name)
    return name


def _stm_chat_id() -> str:
    """Whose memory this session is talking to.

    **The identity of the connection, not a global one.** It is set once at the
    handshake — from the app's token, or from the robot's pairing record — and
    everything this session reads or writes is scoped to it.

    It used to resolve `users_store.get_or_create_owner()`: a single account,
    from an environment variable, for every voice session on the server. That
    was invisible while there was one user and catastrophic the moment there
    were two — a second customer would have been handed the first one's diary.

    The fallback below is for a robot nobody has paired yet. It keeps the old
    single-owner behaviour for an existing install, and returns empty for a
    fresh one, which makes her memoryless rather than someone else's.
    """
    ident = get_voice_identity()
    if ident:
        return ident

    # **ما في احتياطي. مجهول يعني بلا ذاكرة — مش ذاكرة حدا تاني.**
    #
    # كان هون رجوع لـ`get_or_create_owner()`، ونيّته إنّ لوحًا غير مربوط يضلّ
    # يشتغل. وهاد اللي صار فعليًّا: اللوح بيعرّف عن حاله باسم جهاز
    # (`sandy-brain-s3`) مش بمعرّف الوحدة، فالبحث عن صاحبه بيرجع فاضي، وبيقع
    # عالاحتياطي — **فحكى للمالك الجديد باسم القديم، وعدّد عليه مهامه**.
    #
    # وبمنتج فيه أكتر من زبون، نفس السطر بيعطي زبونًا يوميات زبون تاني.
    #
    # الاحتياطي كان بيجاوب سؤالًا غلط. السؤال مش «مين على الأغلب؟» — السؤال
    # «مين بالتأكيد؟»، وجوابه لمّا ما نعرف هو **لا أحد**.
    logger.warning("[voice_ws] unidentified session — starting with no memory")
    return ""


def _load_stm_history() -> List[Dict[str, Any]]:
    """Recent turns from **every** channel, not just the voice thread.

    The voice thread and the app's chat threads are separate documents, so
    reading only this one meant the robot could not remember a conversation the
    owner had in the app a minute earlier — and the app could not remember what
    he had just said out loud. Three doors into the same house, three memories.

    The voice thread's own turns are still in here; they are simply no longer
    the only ones.
    """
    chat_id = _stm_chat_id()
    if not chat_id:
        return []
    try:
        from app.agent.graph.graph import _stm_load, recent_turns_for_user
        shared = recent_turns_for_user(chat_id, limit=10)
        if shared:
            return shared
        # Older documents predate the user_id field and cannot be found by it.
        # Falling back keeps memory working through the deploy rather than
        # starting the owner from nothing.
        return _stm_load(chat_id, chat_id)
    except Exception as exc:
        logger.debug("[voice_ws] STM load skipped: %s", exc)
    return []


def _load_stm_context(history: Optional[List[Dict[str, Any]]] = None) -> str:
    """آخر المحادثات من كل القنوات، وكل جملة مكتوب جنبها من وين إجت.

    المصدر مش زينة. المالك بيحكي مع نفس ساندي بتلات طرق، ومنطقي يسأل «إيمتى
    قلتلك هيك؟» — والجواب «بالمكالمة» غير «وإنت واقف قدّامي». بلا الوسم، الذاكرة
    الموحّدة بتصير كومة جُمَل بلا مكان، وهي ما بتقدر تجاوب عن سؤال هي حاضرة فيه.
    """
    # يُمرَّر من فوق لمّا يكون محمّل أصلاً: بناء تعليمات الجلسة كان بينادي
    # `_load_stm_history` مرتين — مرة من هون ومرة من `_voice_memory_context` —
    # يعني نفس القراءة مرّتين بكل بداية مكالمة، وهي على مسار «قال هاي آندي»
    # لحدّ ما تسمع صوتها.
    history = _load_stm_history() if history is None else history
    if not history:
        return ""
    # كل دور للمستخدم كان موسوم باسم المالك — يعني الموديل بيقرا محادثة زبون
    # وكل جملة فيها منسوبة لشخص ما إله علاقة فيها.
    user_label = voice_speaker_label()
    turns = []
    for m in history[-10:]:
        role_label = user_label if m.get("role") == "user" else "Sandy"
        content = m.get("content", "")
        if not content:
            continue
        via = str(m.get("via") or "").strip()
        turns.append(f"[{via}] {role_label}: {content}" if via
                     else f"{role_label}: {content}")
    if turns:
        return "\nآخر المحادثات عبر كل القنوات:\n" + "\n".join(turns)
    return ""


# Tiny in-process cache for the durable session-start seed. The seed is built
# with durable_only=True (stable facts only), so reusing it for a few seconds
# makes reconnects/rapid re-opens effectively instant without staleness risk.


def _voice_memory_context(
    message: str, *, include_semantic: bool,
    stm_history: Optional[List[Dict[str, Any]]] = None,
) -> Optional[str]:
    """Shared rich-context builder for the voice helpers.

    Returns the voice-formatted memory context for the owner chat, or ``None``
    if there's no owner or the context builder is unavailable (caller decides
    the fallback). Centralizes the context_builder/mongo_db imports that used to
    be repeated across the voice helpers.
    """
    chat_id = _stm_chat_id()
    if not chat_id:
        return None

    # Only the session-start seed (empty message, no semantic) is cacheable —
    # per-turn semantic context is query-specific and must never be reused.
    cacheable = message == "" and not include_semantic
    if cacheable:
        cached = _voice_ctx_cache.get(chat_id)
        if cached and (time.monotonic() - cached[0]) < _VOICE_CTX_TTL_S:
            return cached[1]

    try:
        from app.agent.context_builder import build_memory_context, format_for_voice
        from app.db import get_db
        mongo_db = get_db()
        if stm_history is None:
            stm_history = _load_stm_history()
        ctx = build_memory_context(
            chat_id=chat_id,
            user_id=chat_id,
            message=message,
            mongo_db=mongo_db,
            stm_history=stm_history,
            include_semantic=include_semantic,
            # Voice seed = stable facts only. Recent topics/summaries/STM turns
            # are the exact text that resurfaces as phantom replies on the
            # native-audio model, which can't be told to ignore them.
            durable_only=True,
        )
        text = format_for_voice(ctx)
        if cacheable:
            _voice_ctx_cache[chat_id] = (time.monotonic(), text)
            _voice_ctx_cache.move_to_end(chat_id)
            while len(_voice_ctx_cache) > _VOICE_CTX_MAX:
                _voice_ctx_cache.popitem(last=False)
        return text
    except Exception as exc:
        logger.debug("[voice_ws] context_builder skipped: %s", exc)
        return None


def _save_voice_turn(user_text: str, sandy_text: str,
                     user_id: str = "", channel: str = "") -> None:
    """Save voice turn to STM (MongoDB) + update cross-session state.

    الهوية **والقناة** بيوصلوا من الجلسة: هالدالة بتشتغل ع خيط مجمّع مشترك،
    وسياق الجلسة ما بيوصله. بلا الهوية بتنحفظ المحادثة لحساب غلط أو لولا حساب،
    وبلا القناة بتنحفظ كلمة «الصوت» مكان «الروبوت» أو «مكالمة التطبيق» —
    فالمالك يسأل «إيمتى قلتلك؟» وياخد جوابًا عامًّا.
    """
    if user_id:
        set_voice_identity(user_id)
    if channel:
        set_voice_channel(channel)
    chat_id = _stm_chat_id()
    if not chat_id or not user_text or not sandy_text:
        return
    try:
        from app.agent.graph.graph import _stm_save
        _stm_save(chat_id, chat_id, user_text, sandy_text, via=get_voice_channel())
    except Exception as exc:
        logger.debug("[voice_ws] STM save skipped: %s", exc)
    try:
        from app.db import get_db
        from app.agent.session_state import update_session_state
        update_session_state(chat_id, get_db(), platform="voice")
    except Exception:
        logging.getLogger(__name__).debug("ignoring non-critical error", exc_info=True)
