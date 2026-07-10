"""Studio web APIs: project plans (brainstorm) and the unified search box.

Guest/authenticated split everywhere, same as productivity_api: guests see
demo payloads with `demo: true`; every authenticated user gets their own data,
scoped to current_user_id() inside their profile context. The brainstorm
mutating routes require a real account — guests can't start/edit/delete plans.

Endpoints:
  GET    /api/plans                     saved (finished) project plans
  GET    /api/plans/active              the in-progress brainstorm session, if any
  POST   /api/plans/start               {topic} → start a new session
  POST   /api/plans/active/points       {point} → add an idea to the active session
  POST   /api/plans/active/finish       synthesize the active session into a plan
  POST   /api/plans/active/cancel       abandon the active session
  PATCH  /api/plans/<id>                {change} → revise a saved plan
  DELETE /api/plans/<id>                delete a saved plan
  GET    /api/search?q=...              one box across tasks/reminders/plans
"""

from __future__ import annotations

from flask import jsonify, request

from app.api.auth_handlers import require_auth
from app.utils.user_profiles import active_user_profile_context, build_user_profile
import logging

logger = logging.getLogger(__name__)


def _is_guest(claims) -> bool:
    return claims.get("role") == "guest"


def _brainstorm_chat_ids(claims) -> list:
    """The caller's brainstorm chat_id, both string and int forms (legacy docs
    stored numeric Telegram ids)."""
    uid = str(claims.get("user_id") or "")
    ids = [uid]
    if uid.isdigit():
        ids.append(int(uid))
    return ids


_DEMO_SEARCH = {
    "tasks": [{"id": "demo-t1", "text": "تجهيز العرض التقديمي"}],
    "reminders": [{"id": "demo-r1", "text": "موعد طبيب الأسنان", "remind_at": "2026-06-15T16:00:00"}],
    "plans": [{"topic": "خطة تعلم البرمجة", "summary": "ثلاث مراحل خلال شهرين"}],
}


def register_studio_api(app, mongo_db=None):
    # ── Brainstorm plans ─────────────────────────────────────────────────
    @app.route("/api/plans", methods=["GET"])
    @require_auth
    def api_list_plans(claims):
        if _is_guest(claims):
            return jsonify(
                {
                    "items": [
                        {
                            "id": "demo-pl1",
                            "topic": "خطة تعلم البرمجة",
                            "summary": "ثلاث مراحل خلال شهرين مع مشاريع صغيرة",
                            "finished_at": "2026-06-05T20:00:00",
                            "plan_text": "## الهدف\nتعلم أساسيات البرمجة...\n(نموذج تجريبي)",
                        }
                    ],
                    "demo": True,
                }
            ), 200
        items = []
        try:
            if mongo_db is not None:
                for d in (
                    mongo_db["sandy_brainstorms"]
                    .find({"status": "done", "chat_id": {"$in": _brainstorm_chat_ids(claims)}})
                    .sort("finished_at", -1)
                    .limit(30)
                ):
                    items.append(
                        {
                            "id": str(d.get("_id", "")),
                            "topic": d.get("topic", ""),
                            "summary": d.get("summary", ""),
                            "finished_at": str(d.get("finished_at", "") or ""),
                            "plan_text": d.get("plan_text", ""),
                        }
                    )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[StudioAPI] plans list failed: {e}")
        return jsonify({"items": items, "demo": False}), 200

    def _active_payload(active: dict) -> dict:
        return {
            "topic": active.get("topic", ""),
            "points": [p.get("text", "") for p in active.get("points", [])],
            "started_at": str(active.get("started_at", "") or ""),
        }

    @app.route("/api/plans/active", methods=["GET"])
    @require_auth
    def api_plans_active(claims):
        if _is_guest(claims):
            return jsonify({"active": None, "demo": True}), 200
        from app.features import brainstorm

        uid = str(claims.get("user_id") or "")
        active = brainstorm.get_active(uid)
        return jsonify({"active": _active_payload(active) if active else None}), 200

    @app.route("/api/plans/start", methods=["POST"])
    @require_auth
    def api_plans_start(claims):
        if _is_guest(claims):
            return jsonify({"error": "auth_required"}), 403
        from app.features import brainstorm

        topic = ((request.get_json(silent=True) or {}).get("topic") or "").strip()
        if not topic:
            return jsonify({"error": "topic_required"}), 400
        uid = str(claims.get("user_id") or "")
        active = brainstorm.start_session(uid, topic)
        if not active:
            return jsonify({"error": "unavailable"}), 503
        return jsonify({"active": _active_payload(active)}), 200

    @app.route("/api/plans/active/points", methods=["POST"])
    @require_auth
    def api_plans_add_point(claims):
        if _is_guest(claims):
            return jsonify({"error": "auth_required"}), 403
        from app.features import brainstorm

        point = ((request.get_json(silent=True) or {}).get("point") or "").strip()
        if not point:
            return jsonify({"error": "point_required"}), 400
        uid = str(claims.get("user_id") or "")
        count = brainstorm.add_point(uid, point)
        if not count:
            return jsonify({"error": "no_active_session"}), 400
        return jsonify({"ok": True, "count": count}), 200

    @app.route("/api/plans/active/finish", methods=["POST"])
    @require_auth
    def api_plans_finish(claims):
        if _is_guest(claims):
            return jsonify({"error": "auth_required"}), 403
        from app.features import brainstorm
        from app.agent.facade.agent import create_chat_completion

        uid = str(claims.get("user_id") or "")
        result = brainstorm.finish_session(uid, create_chat_completion)
        if not result:
            return jsonify({"error": "no_active_session"}), 400
        plan_text, _, topic = result
        return jsonify({"plan_text": plan_text, "topic": topic}), 200

    @app.route("/api/plans/active/cancel", methods=["POST"])
    @require_auth
    def api_plans_cancel(claims):
        if _is_guest(claims):
            return jsonify({"error": "auth_required"}), 403
        from app.features import brainstorm

        uid = str(claims.get("user_id") or "")
        ok = brainstorm.cancel_session(uid)
        return jsonify({"ok": ok}), 200

    @app.route("/api/plans/<plan_id>", methods=["PATCH"])
    @require_auth
    def api_plans_update(claims, plan_id):
        if _is_guest(claims):
            return jsonify({"error": "auth_required"}), 403
        from bson import ObjectId
        from bson.errors import InvalidId
        from app.features import brainstorm
        from app.agent.facade.agent import create_chat_completion

        change = ((request.get_json(silent=True) or {}).get("change") or "").strip()
        if not change:
            return jsonify({"error": "change_required"}), 400
        try:
            oid = ObjectId(plan_id)
        except (InvalidId, TypeError):
            return jsonify({"error": "not_found"}), 404
        revised = brainstorm.update_plan_by_id(
            _brainstorm_chat_ids(claims), oid, change, create_chat_completion
        )
        if revised is None:
            return jsonify({"error": "not_found"}), 404
        return jsonify({"plan_text": revised}), 200

    @app.route("/api/plans/<plan_id>", methods=["DELETE"])
    @require_auth
    def api_plans_delete(claims, plan_id):
        if _is_guest(claims):
            return jsonify({"error": "auth_required"}), 403
        if mongo_db is None:
            return jsonify({"ok": False}), 200
        from bson import ObjectId
        from bson.errors import InvalidId

        try:
            oid = ObjectId(plan_id)
        except (InvalidId, TypeError):
            return jsonify({"ok": False}), 200
        res = mongo_db["sandy_brainstorms"].delete_one(
            {"_id": oid, "chat_id": {"$in": _brainstorm_chat_ids(claims)}}
        )
        return jsonify({"ok": res.deleted_count > 0}), (200 if res.deleted_count else 404)

    # ── Unified search ───────────────────────────────────────────────────
    @app.route("/api/search", methods=["GET"])
    @require_auth
    def api_unified_search(claims):
        q = (request.args.get("q") or "").strip()
        if not q:
            return jsonify({"error": "q_required"}), 400
        if _is_guest(claims):
            return jsonify({**_DEMO_SEARCH, "demo": True}), 200

        ql = q.lower()
        out = {"tasks": [], "reminders": [], "plans": [], "demo": False}

        with active_user_profile_context(build_user_profile(claims)):
            try:
                from app.features.tasks_store import load_tasks, load_completed_tasks

                for t in load_tasks() + load_completed_tasks():
                    hay = f"{t.get('text','')} {t.get('notes','')} {t.get('project','')}".lower()
                    if ql in hay:
                        out["tasks"].append(
                            {"id": t["id"], "text": t["text"], "done": t["done"]}
                        )
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[StudioAPI] search tasks failed: {e}")

            try:
                from app.features.reminders_store import load_reminders

                for r in load_reminders(max_results=100):
                    if ql in (r.get("text", "") or "").lower():
                        out["reminders"].append(
                            {"id": r["id"], "text": r["text"], "remind_at": r["remind_at"]}
                        )
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[StudioAPI] search reminders failed: {e}")

            try:
                if mongo_db is not None:
                    for d in mongo_db["sandy_brainstorms"].find(
                        {"status": "done", "chat_id": {"$in": _brainstorm_chat_ids(claims)}},
                        {"topic": 1, "summary": 1, "plan_text": 1},
                    ).limit(100):
                        hay = f"{d.get('topic','')} {d.get('summary','')} {d.get('plan_text','')}".lower()
                        if ql in hay:
                            out["plans"].append(
                                {"topic": d.get("topic", ""), "summary": d.get("summary", "")}
                            )
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[StudioAPI] search plans failed: {e}")

        return jsonify(out), 200
