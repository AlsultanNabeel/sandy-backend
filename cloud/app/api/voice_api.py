"""POST /api/voice/tts: Sandy's Gemini voice as WAV, for the app's lip-synced playback.
GET/POST /api/voice/enroll: whether she knows the owner's voice; start learning it from
the robot's next turns (the print must come from the mic it is checked against)."""

from __future__ import annotations

from flask import Response, jsonify, request

from app.api.auth_handlers import require_auth, require_tenant


def register_voice_api(app) -> None:

    @app.route("/api/voice/tts", methods=["POST"])
    @require_auth
    def api_voice_tts(claims):
        body = request.get_json(silent=True) or {}
        text = (body.get("text") or "").strip()
        mood = (body.get("mood") or "neutral").strip() or "neutral"
        if not text:
            return jsonify({"error": "text_required"}), 400

        # حد أمان للطول.
        text = text[:1200]

        from app.integrations.gemini_tts import synthesize_voice_with_gemini

        audio = synthesize_voice_with_gemini(text, mood=mood)
        if not audio:
            return jsonify({"error": "tts_unavailable"}), 503

        return Response(audio, mimetype="audio/wav")

    @app.route("/api/voice/enroll", methods=["GET"])
    @require_tenant
    def api_voice_enroll_status(claims):
        from app.features import speaker_id

        uid = str(claims.get("user_id") or "")
        return jsonify({"enrolled": speaker_id.has_profile(uid),
                        "collecting": speaker_id.enrollment_progress(uid),
                        "needed": speaker_id.ENROLL_CLIPS}), 200

    @app.route("/api/voice/enroll", methods=["POST"])
    @require_tenant
    def api_voice_enroll_start(claims):
        from app.features import speaker_id

        if not speaker_id.is_available():
            return jsonify({"error": "unavailable",
                            "message": "تمييز الصوت مش مفعّل على السيرفر."}), 503
        if not speaker_id.start_enrollment(str(claims.get("user_id") or "")):
            return jsonify({"error": "not_saved"}), 503
        return jsonify({"ok": True, "needed": speaker_id.ENROLL_CLIPS}), 200
