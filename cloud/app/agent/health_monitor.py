"""#1 — Health & Wellness: رصد أنماط السهر.

Sandy ترصد توقيت رسائل المستخدم وتكتشف أنماط السهر المتأخر.
تُحفظ في MongoDB وتُستخدم في soul_node وproactive_context.
"""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from app.db import get_db
from app.utils.tenant_db import scoped
from app.utils.user_profiles import current_user_id

logger = logging.getLogger(__name__)


_COLL = "sandy_activity"


def _coll():
    """The tenant-scoped handle, and the only way into storage here.

    This module used to take `chat_id` and `mongo_db` and write on the raw
    collection with the tenant stamped by hand — the pattern `tenant_db` exists
    to abolish, and the one `ARCHITECTURE_MAP` §2.6 says must never come back on
    a request path. It was invisible to `test_tenant_scoping_guard.py`, so a
    forgotten filter would have been a cross-tenant leak with nothing watching.

    It could not move before: these writers run on background threads and the
    tenant lives in a `ContextVar` that did not cross one. `submit_background`
    carries it now (§2.5), so the scoping works where it is actually called.
    """
    return scoped(get_db(), _COLL, field="chat_id")


_LATE_HOUR_START = 0   # منتصف الليل
_LATE_HOUR_END = 4     # الرابعة صباحاً
_STREAK_THRESHOLD = 3  # عدد الليالي المتتالية للتنبيه


def record_activity(
    now: Optional[datetime] = None,
) -> None:
    """سجّل توقيت النشاط الحالي — يُستدعى من graph.py بشكل خفي."""
    coll = _coll()
    if coll is None:
        return
    try:
        from app.utils.time import USER_TZ
        ts = now or datetime.now(USER_TZ)
        coll.insert_one({
            "user_id": str(current_user_id() or ""),
            "hour": ts.hour,
            "date": ts.strftime("%Y-%m-%d"),
            "created_at": datetime.now(timezone.utc),
        })
    except Exception as exc:
        logger.debug(f"[health_monitor] record failed: {exc}")


def get_late_night_streak(
    days: int = 7,
) -> int:
    """يرجع عدد الليالي المتتالية التي سهر فيها المستخدم بعد منتصف الليل."""
    coll = _coll()
    if coll is None:
        return 0
    try:
        from app.utils.time import USER_TZ
        docs = list(coll.find(
            {"hour": {"$gte": _LATE_HOUR_START, "$lte": _LATE_HOUR_END}},
            {"_id": 0, "date": 1},
            sort=[("created_at", -1)],
            limit=days * 5,
        ))
        if not docs:
            return 0

        # احسب الأيام الفريدة المتتالية
        late_dates = sorted({d["date"] for d in docs}, reverse=True)

        streak = 0
        check = datetime.now(USER_TZ).date()
        for date_str in late_dates:
            d = date.fromisoformat(date_str)
            if d == check or d == check - timedelta(days=1):
                streak += 1
                check = d - timedelta(days=1)
                if streak >= days:
                    break
            else:
                break
        return streak
    except Exception as exc:
        logger.debug(f"[health_monitor] streak check failed: {exc}")
        return 0


def get_sleep_context(
) -> Optional[str]:
    """يرجع context موجز لـ soul_node إذا كان المستخدم سهران متأخراً.

    يرجع None إذا لا يوجد نمط يستحق الذكر.
    """
    try:
        from app.utils.time import USER_TZ
        now = datetime.now(USER_TZ)
        is_late = _LATE_HOUR_START <= now.hour <= _LATE_HOUR_END
        if not is_late:
            return None

        streak = get_late_night_streak()
        if streak >= _STREAK_THRESHOLD:
            return f"[ملاحظة: سهران متأخر {streak} ليالي متتالية — تعامل برفق]"
        if streak >= 1:
            return "[ملاحظة: سهران متأخر الآن]"
        return None
    except Exception:
        return None


def ensure_ttl_index(mongo_db=None, ttl_days: int = 30) -> None:
    """أنشئ الفهارس اللازمة على sandy_activity عند أول تشغيل.

    **على المقبض الخام، مش المنطاق.** هاي بتنشغّل بالإقلاع — قبل ما أي طلب
    يحدّد مستأجر — فـ`scoped()` بترجّع `None` وما بينعمل ولا فهرس أبداً. وحتى
    لو في مستأجر، `ScopedCollection` ما عندها `create_index` أصلاً. الاستثناء
    مكتوب بـ`tenant_db.py`: إنشاء الفهارس بيضلّ ع المقبض الخام.
    """
    if mongo_db is None:
        from app.db import get_db
        mongo_db = get_db()
    if mongo_db is None:
        return
    try:
        coll = mongo_db[_COLL]
        coll.create_index(
            "created_at", expireAfterSeconds=ttl_days * 86400, background=True
        )
        # get_late_night_streak و get_avg_activity_hour بيفلتروا بـ chat_id
        # ويرتّبوا بـ created_at — بدون هالفهرس بيصير مسح كامل للمجموعة
        # (لاحظنا ثانيتين تأخير وقت الفحوصات الليلية).
        coll.create_index(
            [("chat_id", 1), ("created_at", -1)], background=True
        )
    except Exception:
        logger.debug("ignoring non-critical error", exc_info=True)


def get_avg_activity_hour(
    days: int = 7,
) -> Optional[float]:
    """يرجع متوسط ساعة النشاط خلال آخر N أيام — يُستخدم في Anomaly Detection."""
    coll = _coll()
    if coll is None:
        return None
    try:
        docs = list(coll.find(
            {},
            {"_id": 0, "hour": 1},
            sort=[("created_at", -1)],
            limit=days * 10,
        ))
        if len(docs) < 5:
            return None
        # Hour is circular (23 and 1 are close), so a plain mean is wrong.
        # Average the hours as unit vectors, then convert the angle back.
        angles = [d["hour"] / 24.0 * 2 * math.pi for d in docs]
        mean_sin = sum(math.sin(a) for a in angles) / len(angles)
        mean_cos = sum(math.cos(a) for a in angles) / len(angles)
        avg = math.atan2(mean_sin, mean_cos) / (2 * math.pi) * 24.0
        return avg % 24.0
    except Exception:
        return None
