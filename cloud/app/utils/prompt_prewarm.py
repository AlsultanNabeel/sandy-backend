"""بناء تعليمات الصوت بالخلفية وقت الكتابة، عشان المكالمة الجاية تلاقيها جاهزة.

كل حفظ بيحرّك نسخة المستأجر وبيبطّل الكاش، فمنبني بعد تأخير بسيط، مرّة لكل
مستأجر، وبس للي بيستعملوا الصوت.
"""
from __future__ import annotations

import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

# الدور الواحد بيكتب أكتر من مرّة؛ منستنّى لتهدى الكتابات.
_DELAY_S = float(os.getenv("SANDY_PREWARM_DELAY_S", "2"))

_pending: set[str] = set()
_lock = threading.Lock()
# مستأجرين عندهم مكالمة مفتوحة بهالعمليّة، وكم وحدة.
_live: dict[str, int] = {}
# ومين انكتبله إشي وهو بالمكالمة — بيتسخّن مرّة وحدة لمّا تخلص.
_dirty: set[str] = set()


def hold(tenant: str) -> None:
    """مكالمة بلّشت — أجّل التسخين لحد ما تخلص (كل دور بيحفظ، وبناء واحد بالآخر بيكفي)."""
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
    """كتابة صارت — جهّز تعليماته بالخلفية؛ ما بتفشّل مسار الكتابة أبدًا."""
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
        # قبل البناء: كتابة بتيجي خلاله لازم تجدوِل بناءً جديد.
        with _lock:
            _pending.discard(tenant)

    from app.api.voice_ws.tools import (
        _build_cached_instruction,
        tenant_uses_voice,
    )
    from app.utils.tenant_version import detach_turn_memo

    # المهمّة بتورث ذاكرة دور الكاتب، وفيها رقم النسخة القديم؛ اقرا من القاعدة.
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
