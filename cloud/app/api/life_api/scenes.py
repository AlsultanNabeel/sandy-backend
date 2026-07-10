"""حياتي API — scenes routes."""
from flask import jsonify, request

from app.api.auth_handlers import require_auth, require_tenant
from app.api.life_api._common import _DEMO, _is_guest
from app.utils.user_profiles import active_user_profile_context, build_user_profile


def _register_scenes(app):
    # ── مشاهد الغرفة + التركيز ───────────────────────────────────────────
    @app.route("/api/life/scenes", methods=["GET"])
    @require_auth
    def api_scenes(claims):
        if _is_guest(claims):
            return jsonify({"items": _DEMO["scenes"], "demo": True}), 200
        from app.features.scene_store import list_scenes

        with active_user_profile_context(build_user_profile(claims)):
            items = list_scenes()
        return jsonify({"items": items, "demo": False}), 200

    @app.route("/api/life/scenes", methods=["POST"])
    @require_tenant
    def api_scene_add(claims):
        body = request.get_json(silent=True) or {}
        from app.features.scene_store import add_scene

        r = add_scene(
            (body.get("name") or "").strip(),
            label=(body.get("label") or "").strip(),
            icon=(body.get("icon") or "🎛️").strip(),
            actions=body.get("actions") or [],
        )
        return jsonify(r), (200 if r.get("ok") else 400)

    @app.route("/api/life/scenes/actions", methods=["POST"])
    @require_tenant
    def api_scene_actions(claims):
        body = request.get_json(silent=True) or {}
        from app.features.scene_store import set_scene_actions

        r = set_scene_actions((body.get("name") or "").strip(), body.get("actions") or [])
        return jsonify(r), (200 if r.get("ok") else 400)

    @app.route("/api/life/scenes/apply", methods=["POST"])
    @require_tenant
    def api_scene_apply(claims):
        body = request.get_json(silent=True) or {}
        from app.features.scene_store import apply_scene

        name = (body.get("name") or "").strip()
        r = apply_scene(name)
        # فعّل المشهد فعليًا على الروم-نود عبر MQTT — للمالك فقط (غرفته
        # الفيزيائية). غير المالك يحفظ/يعرض مشاهده هو بس بدون تحكّم بغرفة
        # المالك. انتقالي حتى تجي أدوات التحكّم لكل مستأجر (المرحلة الخامسة).
        online = False
        if r.get("ok"):
            from app.agent.tools.schemas.life_tools import actuate_scene_actions

            online = actuate_scene_actions(r.get("actions") or [])
        r["online"] = online
        return jsonify(r), (200 if r.get("ok") else 404)

    @app.route("/api/life/scenes/delete", methods=["POST"])
    @require_tenant
    def api_scene_delete(claims):
        body = request.get_json(silent=True) or {}
        from app.features.scene_store import delete_scene

        r = delete_scene((body.get("name") or "").strip())
        return jsonify(r), (200 if r.get("ok") else 404)

    @app.route("/api/life/focus", methods=["GET"])
    @require_auth
    def api_focus_status(claims):
        if _is_guest(claims):
            return jsonify({"active": False, "demo": True}), 200
        from app.features.focus_store import focus_status

        with active_user_profile_context(build_user_profile(claims)):
            return jsonify(focus_status()), 200

    @app.route("/api/life/focus/start", methods=["POST"])
    @require_tenant
    def api_focus_start(claims):
        body = request.get_json(silent=True) or {}
        from app.features.focus_store import start_focus

        r = start_focus(
            focus_min=int(body.get("focus_min", 25) or 25),
            label=(body.get("label") or "").strip(),
            break_min=int(body.get("break_min", 0) or 0),
            cycles=int(body.get("cycles", 1) or 1),
            scene=(body.get("scene") or "").strip(),
            end_scene=(body.get("end_scene") or "").strip(),
        )
        return jsonify(r), (200 if r.get("ok") else 400)

    @app.route("/api/life/focus/stop", methods=["POST"])
    @require_tenant
    def api_focus_stop(claims):
        body = request.get_json(silent=True) or {}
        from app.features.focus_store import stop_focus

        r = stop_focus(completed=not bool(body.get("cancel")))
        return jsonify(r), (200 if r.get("ok") else 404)

    @app.route("/api/life/focus/history", methods=["GET"])
    @require_tenant
    def api_focus_history(claims):
        from app.features.focus_store import focus_history

        try:
            limit = int(request.args.get("limit", 50))
        except (TypeError, ValueError):
            limit = 50
        return jsonify({"sessions": focus_history(limit)}), 200

    @app.route("/api/life/focus/stats", methods=["GET"])
    @require_tenant
    def api_focus_stats(claims):
        from app.features.focus_store import focus_stats

        return jsonify(focus_stats()), 200

    @app.route("/api/life/focus/goals", methods=["GET"])
    @require_tenant
    def api_focus_goals(claims):
        from app.features.focus_store import get_focus_goals

        return jsonify(get_focus_goals()), 200

    @app.route("/api/life/focus/goals", methods=["POST"])
    @require_tenant
    def api_focus_goal_set(claims):
        body = request.get_json(silent=True) or {}
        from app.features.focus_store import set_focus_goal

        r = set_focus_goal((body.get("period") or "").strip(),
                           int(body.get("minutes", 0) or 0))
        return jsonify(r), (200 if r.get("ok") else 400)

    @app.route("/api/life/focus/sounds", methods=["GET"])
    @require_tenant
    def api_focus_sounds(claims):
        from app.features.focus_store import get_focus_sounds

        return jsonify(get_focus_sounds()), 200

    @app.route("/api/life/focus/sounds", methods=["POST"])
    @require_tenant
    def api_focus_sound_set(claims):
        body = request.get_json(silent=True) or {}
        from app.features.focus_store import set_focus_sound

        r = set_focus_sound((body.get("event") or "").strip(), (body.get("melody") or "").strip())
        return jsonify(r), (200 if r.get("ok") else 400)
