"""Studio web APIs: project plans and the unified search box.

Guest/authenticated split everywhere, same as productivity_api: guests see
demo payloads with `demo: true`; every authenticated user gets their own data,
scoped to current_user_id() inside their profile context.

Endpoints:
  GET  /api/plans               saved project plans
  GET  /api/search?q=...        one box across tasks/reminders/plans
"""

from __future__ import annotations

from flask import jsonify, request

from app.api.auth_handlers import require_auth
from app.utils.user_profiles import active_user_profile_context, build_user_profile


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
            print(f"[StudioAPI] plans list failed: {e}")
        return jsonify({"items": items, "demo": False}), 200

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
                print(f"[StudioAPI] search tasks failed: {e}")

            try:
                from app.features.reminders_store import load_reminders

                for r in load_reminders(max_results=100):
                    if ql in (r.get("text", "") or "").lower():
                        out["reminders"].append(
                            {"id": r["id"], "text": r["text"], "remind_at": r["remind_at"]}
                        )
            except Exception as e:  # noqa: BLE001
                print(f"[StudioAPI] search reminders failed: {e}")

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
                print(f"[StudioAPI] search plans failed: {e}")

        return jsonify(out), 200
