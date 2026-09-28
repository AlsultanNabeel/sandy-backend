"""POST /api/voice/tts: Sandy's Gemini voice as WAV, for the app's lip-synced playback."""

from __future__ import annotations

from flask import Response, jsonify, request

from app.api.auth_handlers import require_auth


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
