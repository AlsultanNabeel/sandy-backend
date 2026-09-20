"""ذاكرة الأسلوب: Sandy بتتعلّم تفضيلات المستخدم وتصحيحاته وبتطبّقها.

بنحفظ التفضيل عبر save_style_preference() لما المستخدم يقول شي زي
"ما أريد كذا" أو "فضّلي كذا".
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from app.db import get_db
from app.utils.tenant_db import scoped

logger = logging.getLogger(__name__)

_COLL = "sandy_memories"
_LABEL = "style_memory"

# كلمات بتدل على تصحيح أسلوبي. لازم تيجي ببداية كلمة: كـ substring كانت «أطل»
# بتلقط «بدي أطلب…» و«فضلي» بتلقط «تفضلي»، وكل رسالة منهن كانت تنحفظ
# «تفضيل أسلوب» وتنحقن بالبرسونا بكل رد بعدها.
CORRECTION_SIGNALS = [
    "لا تستخدم", "لا تكتب", "ما أريد", "ما أحب", "ما يعجبني",
    "قلل", "طوّل", "اختصر", "بدون رموز", "بدون ايموجي",
    "ردودك طويلة", "ردودك قصيرة", "بدي ردود", "أريدك أن", "فضلي",
    "تذكري إني", "خليك", "كوني",
]
_CORRECTION_RE = re.compile(
    r"(?:^|\s)(?:" + "|".join(re.escape(s) for s in CORRECTION_SIGNALS) + ")"
)


def save_style_preference(preference: str, source_message: str = "") -> bool:
    """يحفظ تفضيل أسلوب جديد في MongoDB.

    بيستدعيه الـ graph pipeline لما يكتشف رسالة تصحيح. يرجّع True لو نجح.
    The write goes through the tenant-scoped handle, which also bumps the
    tenant version — the `style_memory` label feeds the cached persona block,
    and without the bump «اختصري» would not reach her next reply.
    """
    coll = scoped(get_db(), _COLL, field="chat_id")
    if coll is None or not (preference or "").strip():
        return False
    try:
        from app.agent.ltm_crypto import encrypt_field
        from app.utils.user_profiles import current_user_id

        coll.insert_one({
            "user_id": str(current_user_id() or ""),
            "label": _LABEL,
            "preference": encrypt_field(str(preference).strip()[:300]),
            "source_message": encrypt_field(str(source_message)[:200]),
            "created_at": datetime.now(timezone.utc),
        })
        logger.info("[style_memory] saved preference")
        return True
    except Exception as exc:
        logger.warning("[style_memory] save failed: %s", exc)
        return False


def detect_style_correction(message: str) -> bool:
    """يشوف لو الرسالة فيها تصحيح أسلوبي.

    بيستدعيه graph.py بالخلفية بعد الرد (مش على مسار الرد).
    """
    return bool(_CORRECTION_RE.search(message or ""))
