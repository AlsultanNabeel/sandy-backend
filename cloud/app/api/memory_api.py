"""Memory API — what Sandy remembers about you (the user-facing memory view).

Surfaces the user's stored facts (`sandy_facts`), scoped to their own data. It
deliberately EXCLUDES Sandy's system/automatic memory — the rolling conversation
summaries in `sandy_memories` ("منظومة ساندي") are internal plumbing, not
user-facing facts. Real data only; no demo payloads.

Endpoints:
  GET    /api/memory            this user's stored facts
  DELETE /api/memory/<fact_id>  forget one fact
"""

from __future__ import annotations

from flask import jsonify

from app.api.auth_handlers import require_auth
from app.utils.user_profiles import active_user_profile_context, build_user_profile


def register_memory_api(app):
    @app.route("/api/memory", methods=["GET"])
    @require_auth
    def get_memory(claims):
        from app.agent.semantic_memory import list_user_facts

        with active_user_profile_context(build_user_profile(claims)):
            items = list_user_facts()
        return jsonify({"items": items}), 200

    @app.route("/api/memory/<fact_id>", methods=["DELETE"])
    @require_auth
    def delete_memory(claims, fact_id):
        from app.agent.semantic_memory import delete_user_fact

        with active_user_profile_context(build_user_profile(claims)):
            ok = delete_user_fact(fact_id)
        return jsonify({"ok": ok}), 200
