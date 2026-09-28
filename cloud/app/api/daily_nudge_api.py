"""Daily nudge: alternates a get-to-know-you question with an LLM agenda line, cached per day.

  GET  /api/daily-nudge         today's nudge
  POST /api/daily-nudge/answer  {qid, answer}
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from flask import jsonify, request

from app.api.auth_handlers import require_auth, require_tenant
from app.utils.tenant_db import scoped
from app.utils.time import USER_TZ
from app.utils.user_profiles import (
    active_user_profile_context,
    build_user_profile,
    current_user_id,
)

logger = logging.getLogger(__name__)

_COLL = "sandy_daily_nudge"

# Asked in order, every other day.
_QUESTIONS: List[Dict[str, str]] = [
    {"id": "unwind", "text": "شو أكتر إشي بيريّحك بعد يوم طويل؟"},
    {"id": "peak", "text": "إنت أنشط الصبح ولا الليل؟"},
    {"id": "procrastinate", "text": "شو الإشي اللي دايماً بتأجّله وودّك تخلّصه؟"},
    {"id": "important_person", "text": "مين أهم شخص ما بدك تنسى مناسباته؟"},
    {"id": "one_reminder", "text": "لو بذكّرك بإشي وحيد كل يوم، شو بدك يكون؟"},
    {"id": "hobby", "text": "شو هوايتك اللي نفسك ترجعلها؟"},
]

_AGENDA_INSTRUCTION = (
    "\n\nاكتبي إشعاراً يومياً واحداً قصيراً (جملة أو جملتين) بصوتك، ذكياً وغير "
    "مكرر أبداً. لو يوم المستخدم مضغوط (مهام كثيرة أو متأخرة) نبّهيه بلطف إنه ما "
    "يتقاعس وحمّسيه يبلّش؛ لو خفيف طمّنيه وشجّعيه ياخد نفَس. "
    "بلا قوائم ولا رموز نقطية — جملة طبيعية دافئة."
)
# The address line is added per call from the active profile (address_instruction).


def _today() -> str:
    return datetime.now(USER_TZ).strftime("%Y-%m-%d")


def _is_question_day() -> bool:
    """A question every other day; an agenda line on the days in between."""
    return datetime.now(USER_TZ).toordinal() % 2 == 0


def _next_question(uid: str) -> Optional[Dict[str, str]]:
    from app.features import users_store
    answered = users_store.get_nudge_answers(uid) or {}
    for q in _QUESTIONS:
        if q["id"] not in answered:
            return q
    return None


def _was_up_late(mongo_db, uid: str) -> bool:
    """True if the user was active 00:00–04:59 local recently (from session_state.last_active_at)."""
    try:
        from app.agent.session_state import get_session_state
        ss = get_session_state(uid, mongo_db) or {}
        la = ss.get("last_active_at")
        if not isinstance(la, datetime):
            return False
        if la.tzinfo is None:
            la = la.replace(tzinfo=timezone.utc)
        local = la.astimezone(USER_TZ)
        now = datetime.now(USER_TZ)
        return local.hour < 5 and (now - local).total_seconds() < 18 * 3600
    except Exception as exc:  # noqa: BLE001
        logger.debug("[daily_nudge] late-night check failed: %s", exc)
        return False


def _load_summary(mongo_db, uid: str) -> Dict[str, Any]:
    from app.features import reminders_store, tasks_store
    tasks = tasks_store.load_tasks(mongo_db=mongo_db) or []
    overdue = tasks_store.overdue_among(tasks)
    reminders = reminders_store.load_reminders(max_results=20) or []
    titles = [
        str(t.get("text", "")).strip()
        for t in (list(overdue)[:2] + list(tasks)[:3])
        if str(t.get("text", "")).strip()
    ]
    return {
        "tasks": len(tasks),
        "overdue": len(overdue),
        "reminders": len(reminders),
        "titles": titles,
        "late": _was_up_late(mongo_db, uid),
    }


def _generate_agenda(uid: str, summary: Dict[str, Any]) -> str:
    """LLM agenda line in the user's persona, with a template fallback."""
    load_line = (
        f"مهام نشطة: {summary['tasks']}، متأخرة: {summary['overdue']}، "
        f"تذكيرات: {summary['reminders']}."
    )
    titles = summary.get("titles") or []
    heavy = summary["overdue"] > 0 or (summary["tasks"] + summary["overdue"]) >= 4
    late = bool(summary.get("late"))
    try:
        from app.agent.context_builder import build_effective_persona
        from app.agent.facade.agent import create_chat_completion
        from app.utils.user_profiles import address_instruction
        system = build_effective_persona(uid) + _AGENDA_INSTRUCTION + "\n" + address_instruction()
        user = load_line + (" أبرز العناوين: " + "؛ ".join(titles) if titles else "")
        if late:
            user += (
                " (ملاحظة: كان ساهر لوقت متأخر مبارح — ابدئي بصباح دافئ واسأليه "
                "بلطف كيف نام وكيف حاله بعد السهر قبل ما تحكي عن المهام.)"
            )
        result = create_chat_completion(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=120,
        )
        text = result if isinstance(result, str) else result.choices[0].message.content
        text = (text or "").strip()
        if text:
            return text
    except Exception as exc:  # noqa: BLE001
        logger.debug("[daily_nudge] LLM agenda failed, using fallback: %s", exc)

    greet = "صباح الخير 🌙 كيفك بعد السهرة؟" if late else "صباح الخير 🌤️"
    if summary["tasks"] == 0 and summary["overdue"] == 0:
        return f"{greet} يومك فاضي — خليك مرتاح، وإذا حابب نخطّط لبكرا؟"
    lead = titles[0] if titles else "مهامك"
    tone = "يومك مضغوط شوي، بلاش تقاعس 💪" if heavy else "يومك محتمل، خليك ماشي 🙂"
    return (
        f"{greet} {tone} عندك اليوم {summary['tasks']} مهمة "
        f"و{summary['reminders']} تذكير — أهمها: {lead}."
    )


def get_daily_nudge(mongo_db, uid: str) -> Dict[str, Any]:
    """Today's nudge, generated once per day; needs the user's profile context. Shared with the push scheduler."""
    # bump=False: the nudge feeds nothing the persona cache is built from.
    coll = scoped(mongo_db, _COLL, bump=False)
    key = f"{uid}:{_today()}"
    if coll is not None:
        cached = coll.find_one({"_id": key})
        if cached and cached.get("nudge"):
            return cached["nudge"]

    q = _next_question(uid) if _is_question_day() else None
    if q is not None:
        nudge: Dict[str, Any] = {"kind": "question", "qid": q["id"], "text": q["text"]}
    else:
        nudge = {"kind": "agenda", "text": _generate_agenda(uid, _load_summary(mongo_db, uid))}

    if coll is not None:
        try:
            coll.update_one(
                {"_id": key},
                {"$set": {"nudge": nudge, "created_at": datetime.now(timezone.utc)}},
                upsert=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("[daily_nudge] cache write failed: %s", exc)
    return nudge


def register_daily_nudge_api(app, mongo_db=None):
    if mongo_db is not None:
        try:
            mongo_db[_COLL].create_index(
                "created_at", expireAfterSeconds=60 * 60 * 24 * 3, background=True
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("[daily_nudge] index skipped: %s", exc)

    @app.route("/api/daily-nudge", methods=["GET"])
    @require_auth
    def api_daily_nudge(claims):
        if claims.get("role") == "guest":
            return jsonify({"kind": "none"}), 200
        with active_user_profile_context(build_user_profile(claims)):
            uid = current_user_id()
            if not uid:
                return jsonify({"kind": "none"}), 200
            return jsonify(get_daily_nudge(mongo_db, uid)), 200

    @app.route("/api/daily-nudge/answer", methods=["POST"])
    @require_tenant
    def api_daily_nudge_answer(claims):
        body = request.get_json(silent=True) or {}
        qid = str(body.get("qid") or "").strip()
        answer = str(body.get("answer") or "").strip()
        if not qid or not answer:
            return jsonify({"error": "bad_request"}), 400
        from app.features import users_store
        uid = current_user_id()
        ok = users_store.record_nudge_answer(uid, qid, answer) if uid else False
        return (jsonify({"ok": True}), 200) if ok else (jsonify({"error": "save_failed"}), 400)
