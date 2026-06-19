"""Owner Telegram notifier — a tiny stateless client.

Extracted from the old ``project_builder/notifier.py`` (general owner-notify
part only; the build/CI-specific notifications went away with self-coding).
Used by the incident tracker to alert the owner when it auto-opens an issue.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_NOTIF_PREFIX = "🔔 "


def _get_bot():
    """Lazy import telebot + build client. None if not configured."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return None
    try:
        import telebot  # type: ignore
        return telebot.TeleBot(token, parse_mode=None)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[owner_notify] telebot init failed: %s", exc)
        return None


def get_owner_chat_id() -> Optional[str]:
    val = (os.getenv("OWNER_CHAT_ID") or os.getenv("SANDY_USER_CHAT_ID") or "").strip()
    return val or None


def notify_owner(message: str, *, chat_id: Optional[str] = None) -> bool:
    """Send a prefixed notification to the owner (or provided chat_id)."""
    cid = chat_id or get_owner_chat_id()
    if not cid:
        logger.warning("[owner_notify] OWNER_CHAT_ID غير مضبوط — skip")
        return False
    bot = _get_bot()
    if bot is None:
        return False
    try:
        text = message if message.startswith(_NOTIF_PREFIX) else _NOTIF_PREFIX + message
        bot.send_message(int(cid) if str(cid).lstrip("-").isdigit() else cid, text)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("[owner_notify] send_message failed: %s", exc)
        return False
