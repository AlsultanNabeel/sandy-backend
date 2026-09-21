"""بناء تعليمات الصوت **قبل** المكالمة، مش وقتها.

السجل من مكالمة حقيقية:

    [voice_ws] instruction rebuilt (version 165, shared row absent)
    [voice_ws] seed persona: 251ms
    [voice_ws] seed context: 4900ms
    [voice_ws] session open: seed=5664ms dial=993ms total=6657ms ... cached=no

خمس ثواني من أصل ستة ونصّ، وصاحبها مستني عالخط. والكاش موجود وشغّال — بس
مفتاحه نسخة المستأجر، وآخر إشي بتعمله أي مكالمة هو إنها بتحفظ اللي انحكى
وبتستخرج منه حقائق، والحفظ بيحرّك النسخة. يعني **كل مكالمة بتبطّل صلاحية كاش
المكالمة اللي بعدها**، والكاش بيضلّ بارد للأبد بالتصميم.

الحلّ مش تضعيف الإبطال — الإبطال صح، وبدونه بتحكي عن مهمّة انحذفت. الحلّ إنّ
إعادة البناء تصير وقت الكتابة، بالخلفية، والمكالمة الجاية تلاقيها جاهزة.

تلات احتياطات:
  • **تأخير بسيط**: الدور الواحد بيكتب أكتر من مرّة (مهمّة، تفضيل، ملخّص)، فلو
    بنينا ع كل كتابة بنبني تلات مرّات ونرمي تنتين. منستنّى شوي لتهدى الكتابات.
  • **واحد لكل مستأجر**: لو في بناء مجدوَل، الكتابة الجديدة بتركب عليه.
  • **للي بيستعملوا الصوت بس**: زبون ما فتح مكالمة بحياته ما في سبب نبنيلو
    تعليمات صوت كل ما يضيف مهمّة. العلامة بتنكتب أول مرّة بتنبنى فيها فعلاً.
"""
from __future__ import annotations

import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

# قدّيش منستنّى لتهدى كتابات الدور الواحد قبل ما نبني.
_DELAY_S = float(os.getenv("SANDY_PREWARM_DELAY_S", "2"))

_pending: set[str] = set()
_lock = threading.Lock()
# مستأجرين عندهم مكالمة مفتوحة بهالعمليّة، وكم وحدة.
_live: dict[str, int] = {}
# ومين انكتبله إشي وهو بالمكالمة — بيتسخّن مرّة وحدة لمّا تخلص.
_dirty: set[str] = set()


def hold(tenant: str) -> None:
    """مكالمة بلّشت — أجّل التسخين لحد ما تخلص.

    **كل دور بالمكالمة بيحفظ ذاكرة، والحفظ بيطلق بناء.** السجل: «نسخة مية وتلاتة
    وتلاتين»، بناء ثانية كاملة، بنصّ مكالمة شغّالة وعلى نفس السيرفر — لمكالمة لسا
    ما صارت. عشر أدوار = عشر بناءات، تسعة منهم بينرموا. بناء واحد بالآخر بيكفي.
    """
    key = str(tenant or "")
    if not key:
        return
    with _lock:
        _live[key] = _live.get(key, 0) + 1


def release(tenant: str) -> None:
    """المكالمة خلصت — لو انكتب إشي خلالها، هلّق وقت البناء."""
    key = str(tenant or "")
    if not key:
        return
    with _lock:
        left = _live.get(key, 0) - 1
        if left > 0:
            _live[key] = left
            return
        _live.pop(key, None)
        dirty = key in _dirty
        _dirty.discard(key)
    if dirty:
        schedule(key)


def schedule(tenant: str) -> None:
    """كتابة صارت لهالمستأجر — جهّز تعليماته للمكالمة الجاية.

    بترجع فورًا: كل الشغل ع مجمّع الخلفية، وما بتعلّق مسار الكتابة ولا بتفشّله.
    """
    key = str(tenant or "")
    if not key:
        return
    with _lock:
        if key in _live:
            _dirty.add(key)
            return
        if key in _pending:
            return
        _pending.add(key)
    try:
        from app.utils.thread_pool import submit_background

        submit_background(_warm, key, _label="prompt-prewarm")
    except Exception:  # noqa: BLE001 — التسخين رفاهية، ما بيوقف كتابة
        with _lock:
            _pending.discard(key)
        logger.debug("[prewarm] could not schedule", exc_info=True)


def _warm(tenant: str) -> None:
    try:
        time.sleep(_DELAY_S)
    finally:
        # قبل البناء، مش بعده: كتابة إجت وإحنا عم نبني لازم تجدوِل بناءً جديد،
        # لأنّ اللي عم نبنيه هلّق صار قديم.
        with _lock:
            _pending.discard(tenant)

    from app.api.voice_ws.tools import (
        _build_cached_instruction,
        tenant_uses_voice,
    )
    from app.utils.tenant_version import detach_turn_memo

    # **نسخة المستأجر تتقرا من القاعدة، لا من ذاكرة الدور.** المهمّة بتورث سياق
    # اللي كتب، وفيه رقم النسخة المحفوظ لذاك الدور — وهاد بالضبط الرقم القديم.
    detach_turn_memo()

    if not tenant_uses_voice(tenant):
        return
    t0 = time.monotonic()
    try:
        _build_cached_instruction(tenant)
    except Exception:  # noqa: BLE001
        logger.debug("[prewarm] build failed", exc_info=True)
        return
    logger.info("[prewarm] voice instruction ready in %.0fms — the next call "
                "will not pay for it", (time.monotonic() - t0) * 1000)
