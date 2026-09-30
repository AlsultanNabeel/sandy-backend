"""Web API for room scenes and focus sessions (the rest of حياتي lives on the blocks)."""

from __future__ import annotations

from flask import jsonify, request

from app.api.auth_handlers import require_tenant


def body_int(body: dict, key: str, default: int = 0) -> int:
    """An integer field from a JSON body, or ValidationError (→ 400)."""
    from app.errors import ValidationError

    raw = body.get(key, default)
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ValidationError(f"{key} must be a whole number") from None


def register_life_api(app):
    # ── مشاهد الغرفة + التركيز ───────────────────────────────────────────
    @app.route("/api/life/scenes", methods=["GET"])
    @require_tenant
    def api_scenes(claims):
        from app.features.scene_store import list_scenes

        return jsonify({"items": list_scenes(), "demo": False}), 200

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
        from app.features.scene_store import actuate_scene_actions, apply_scene

        name = (body.get("name") or "").strip()
        r = apply_scene(name)
        # فعّل المشهد على أجهزة هالمستأجر؛ البوابة ملكية الموضوع (tenant_owns_topic).
        online = False
        if r.get("ok"):
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
    @require_tenant
    def api_focus_status(claims):
        from app.features.focus_store import focus_status

        return jsonify(focus_status()), 200

    @app.route("/api/life/focus/start", methods=["POST"])
    @require_tenant
    def api_focus_start(claims):
        body = request.get_json(silent=True) or {}
        from app.features.focus_store import start_focus

        r = start_focus(
            focus_min=body_int(body, "focus_min", 25),
            label=(body.get("label") or "").strip(),
            break_min=body_int(body, "break_min"),
            cycles=body_int(body, "cycles", 1),
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
