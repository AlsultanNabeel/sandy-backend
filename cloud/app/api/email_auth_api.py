"""Email/password auth — register + login.

A self-contained alternative to social sign-in (Apple/Google) for users who
don't want a provider account. Passwords are hashed with werkzeug (never stored
in plain text), and a successful register/login mints the SAME app JWT as the
social endpoints, so the rest of the API treats these users identically
(``role="user"`` scoped by ``user_id``).

Endpoints:
  POST /api/auth/email/register  {email, password}      -> {token, user_id, role, onboarding_done}
  POST /api/auth/email/login     {email, password}      -> {token, user_id, role, onboarding_done}
"""

from __future__ import annotations

import re

from flask import jsonify, request
from werkzeug.security import generate_password_hash, check_password_hash

from app.api.auth_handlers import make_token
from app.features import users_store

# تحقّق إيميل بسيط (شكل عام) — التحقّق الحقيقي يصير عند الاستعمال.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MIN_PASSWORD = 8


def _result_for(user):
    """يصكّ توكن التطبيق لمستخدم ويرجّع نفس شكل ردّ المصادقة الاجتماعية."""
    user_id = user.get("_id")
    try:
        token = make_token("user", user_id=user_id)
    except RuntimeError:
        return jsonify({"error": "auth_unavailable"}), 503
    onboarding = user.get("onboarding") or {}
    return jsonify({
        "token": token,
        "user_id": user_id,
        "role": "user",
        "onboarding_done": bool(onboarding.get("done", False)),
    }), 200


def register_email_auth_api(app):
    @app.route("/api/auth/email/register", methods=["POST"])
    def api_email_register():
        body = request.get_json(silent=True) or {}
        email = str(body.get("email") or "").strip().lower()
        password = str(body.get("password") or "")

        if not _EMAIL_RE.match(email):
            return jsonify({"error": "invalid_email"}), 400
        if len(password) < _MIN_PASSWORD:
            return jsonify({"error": "weak_password"}), 400
        if users_store.get_email_user(email):
            return jsonify({"error": "email_taken"}), 409

        user = users_store.create_email_user(email, generate_password_hash(password))
        if not user:
            return jsonify({"error": "auth_unavailable"}), 503
        return _result_for(user)

    @app.route("/api/auth/email/login", methods=["POST"])
    def api_email_login():
        body = request.get_json(silent=True) or {}
        email = str(body.get("email") or "").strip().lower()
        password = str(body.get("password") or "")

        user = users_store.get_email_user(email)
        if not user or not check_password_hash(user.get("password_hash") or "", password):
            # نفس الردّ للإيميل الغلط والباسوورد الغلط (ما نكشف وجود الحساب).
            return jsonify({"error": "invalid_credentials"}), 401
        return _result_for(user)
