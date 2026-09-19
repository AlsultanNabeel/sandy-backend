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

from app.api.auth_handlers import check_rate_limit, make_token
from app.features import users_store

# تحقّق إيميل بسيط (شكل عام) — التحقّق الحقيقي يصير عند الاستعمال.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MIN_PASSWORD = 8


def _client_ip() -> str:
    """The address that actually connected, as Heroku's router saw it.

    **The last entry, not the first.** `X-Forwarded-For` arrives from the client
    and Heroku's router *appends* the connecting address to whatever was there.
    The first entry is therefore whatever the caller chose to send — reading it
    let a password-guessing script name a fresh "IP" on every request and never
    meet the per-IP limit. The last one is the only entry nobody but the router
    wrote.
    """
    forwarded = [h.strip() for h in
                 request.headers.get("X-Forwarded-For", "").split(",") if h.strip()]
    return forwarded[-1] if forwarded else (request.remote_addr or "unknown")


def _rate_blocked(*checks) -> bool:
    """True لو أي (key, scope) تجاوز الحدّ — يمنع تخمين الباسوردات وسبام التسجيل.
    نفحص بالأيبي (حشو اعتماد) وبالإيميل (تخمين موجّه من عناوين متغيّرة)."""
    for key, scope in checks:
        allowed, _ = check_rate_limit(key, scope=scope)
        if not allowed:
            return True
    return False


def _result_for(user):
    """يصكّ توكن التطبيق لمستخدم ويرجّع نفس شكل ردّ المصادقة الاجتماعية."""
    user_id = user.get("_id")
    # Never the owner tier here. Nothing on this route proves the address
    # belongs to whoever typed it — anyone could register with the owner's
    # email and get his quota. The owner signs in with Google, where the
    # provider has verified the address (social_auth_api).
    role = "user"
    try:
        token = make_token(role, user_id=user_id)
    except RuntimeError:
        return jsonify({"error": "auth_unavailable"}), 503
    onboarding = user.get("onboarding") or {}
    return jsonify({
        "token": token,
        "user_id": user_id,
        # The role the token carries — this said "user" even for the owner.
        "role": role,
        "onboarding_done": bool(onboarding.get("done", False)),
    }), 200


def register_email_auth_api(app):
    @app.route("/api/auth/email/register", methods=["POST"])
    def api_email_register():
        if _rate_blocked((_client_ip(), "email_register")):
            return jsonify({"error": "too_many_attempts"}), 429
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

        # حدّ بالأيبي وبالإيميل معاً قبل أي فحص باسورد (منع التخمين/الحشو).
        if _rate_blocked(
            (_client_ip(), "email_login"),
            (email or "unknown", "email_login_acct"),
        ):
            return jsonify({"error": "too_many_attempts"}), 429

        user = users_store.get_email_user(email)
        if not user or not check_password_hash(user.get("password_hash") or "", password):
            # نفس الردّ للإيميل الغلط والباسوورد الغلط (ما نكشف وجود الحساب).
            return jsonify({"error": "invalid_credentials"}), 401
        return _result_for(user)
