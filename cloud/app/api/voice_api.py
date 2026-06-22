"""Voice TTS endpoint — Sandy's natural Gemini voice (WAV) for given text.

The iOS app fetches this to play Sandy's real voice and drive her mouth from the
audio amplitude (lip-sync), instead of the phone's robotic on-device synthesizer.

Output: ``audio/wav`` (LINEAR16 PCM @ 22050 Hz, mono) — exactly what
``synthesize_voice_with_gemini`` returns.
"""

from __future__ import annotations

from flask import Response, jsonify, request

from app.api.auth_handlers import require_auth


def register_voice_api(app) -> None:
    """Attach ``POST /api/voice/tts`` to an existing Flask app."""

    @app.route("/api/voice/tts", methods=["POST"])
    @require_auth
    def api_voice_tts(claims):
        body = request.get_json(silent=True) or {}
        text = (body.get("text") or "").strip()
        mood = (body.get("mood") or "neutral").strip() or "neutral"
        if not text:
            return jsonify({"error": "text_required"}), 400

        # حد أمان للطول — ما نطوّل التوليد بلا داعٍ (الردود الصوتية قصيرة عادة).
        text = text[:1200]

        from app.integrations.gemini_tts import synthesize_voice_with_gemini

        audio = synthesize_voice_with_gemini(text, mood=mood)
        if not audio:
            return jsonify({"error": "tts_unavailable"}), 503

        return Response(audio, mimetype="audio/wav")
