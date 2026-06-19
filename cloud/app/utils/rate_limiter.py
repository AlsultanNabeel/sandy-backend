"""Per-user rate limiter — in-process sliding window.

Was Redis-backed; moved fully in-memory when we dropped Redis/Upstash. Rate
limiting is per-process abuse protection (not exact across dynos), which is fine
for this scale and removes the Upstash dependency.

Usage
-----
    from app.utils.rate_limiter import is_rate_limited

    if is_rate_limited(chat_id):
        bot.reply_to(message, "كثير رسائل، خلّيني أتنفس 😅")
        return
"""

import threading
import time
from collections import deque
from typing import Dict

_MAX_MESSAGES: int = 20
_WINDOW_SECONDS: int = 60
_SWEEP_EVERY: int = 1000

# In-memory fallback
_windows: Dict[str, deque] = {}
_lock = threading.Lock()
_calls_count: int = 0


def _sweep_stale_windows(cutoff: float) -> None:
    """حذف المفاتيح التي انتهت صلاحية جميع طوابعها. يُستدعى داخل _lock فقط."""
    stale = [k for k, dq in _windows.items() if not dq or dq[-1] <= cutoff]
    for k in stale:
        del _windows[k]


def is_rate_limited(chat_id: str | int) -> bool:
    """Return True if this chat_id has exceeded _MAX_MESSAGES in the last _WINDOW_SECONDS."""
    global _calls_count

    key = str(chat_id)

    # monotonic() (not time.time()) on purpose: this window is process-local, so a
    # monotonic clock is immune to system time jumps (NTP/DST).
    now = time.monotonic()
    cutoff = now - _WINDOW_SECONDS
    with _lock:
        _calls_count += 1

        if key not in _windows:
            _windows[key] = deque()
        window = _windows[key]
        while window and window[0] <= cutoff:
            window.popleft()

        # حذف المفتاح فور فراغ الـ deque لتحرير الذاكرة
        if not window:
            del _windows[key]
            window = deque()
            _windows[key] = window

        if len(window) >= _MAX_MESSAGES:
            return True
        window.append(now)

        # sweep دوري لتنظيف المستخدمين غير النشطين
        if _calls_count % _SWEEP_EVERY == 0:
            _sweep_stale_windows(cutoff)

        return False


def reset_rate_limit(chat_id: str | int) -> None:
    """Clear the window for a given chat_id (useful for tests)."""
    key = str(chat_id)
    with _lock:
        _windows.pop(key, None)
