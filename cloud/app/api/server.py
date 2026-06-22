import logging
import os
from datetime import datetime, timezone

from flask import Flask, jsonify, request
from flask_cors import CORS

from app.utils import metrics as metrics
from app.utils import metrics_push as metrics_push

from app.agent.semantic_memory import semantic_memory_stats
from app.utils.error_tracking import log_unhandled_exception

logger = logging.getLogger(__name__)


def create_app(
    *,
    mongo_db=None,
    semantic_memory_stats_fn=semantic_memory_stats,
):
    # Imported here (not at module top) so importing this module stays free of
    # the PyJWT dependency until the app is actually built. The decorators below
    # are applied when this factory runs, which is after import.
    from app.api.auth_handlers import (
        check_owner_password,
        check_rate_limit,
        get_access_request,
        make_token,
        require_auth,
        store_access_request,
    )

    app = Flask(__name__)
    CORS(app, resources={r"/api/*": {"origins": os.getenv("FRONTEND_URL", "*")}})

    # Start the Grafana Cloud metrics pusher. It's a no-op if the env vars
    # aren't set, and the thread is daemonized so it dies with the dyno.
    try:
        metrics_push.start_metrics_pusher()
    except Exception as _exc:
        # Pushing metrics is best-effort, don't let it fail startup.
        print(f"[metrics_push] start failed: {_exc}")

    @app.route("/health", methods=["GET"])
    def health():
        mongo_status = {"ok": False, "available": mongo_db is not None}
        if mongo_db is not None:
            try:
                mongo_db.command("ping")
                mongo_status.update(
                    {"ok": True, "database": getattr(mongo_db, "name", None)}
                )
            except Exception as exc:
                mongo_status["error"] = str(exc)

        chroma_status = {"ok": False}
        try:
            chroma_data = semantic_memory_stats_fn() if callable(semantic_memory_stats_fn) else {}
            chroma_status.update({"ok": True, **(chroma_data or {})})
        except Exception as exc:
            chroma_status["error"] = str(exc)

        overall_ok = (
            mongo_status.get("ok")
            and chroma_status.get("ok")
        )
        return jsonify(
            {
                "ok": bool(overall_ok),
                "mongo": mongo_status,
                "chroma": chroma_status,
            }
        ), (200 if overall_ok else 503)

    @app.route("/metrics", methods=["GET"])
    def metrics_endpoint():
        data, content_type = metrics.metrics_wsgi()
        return (data, 200, {
            "Content-Type": content_type,
            "Cache-Control": "no-store",
        })

    from app.api.voice_ws import register_voice_ws
    register_voice_ws(app)

    from app.api.voice_api import register_voice_api
    register_voice_api(app)

    from app.api.productivity_api import register_productivity_api
    register_productivity_api(app, mongo_db=mongo_db)

    from app.api.studio_api import register_studio_api
    register_studio_api(app, mongo_db=mongo_db)

    from app.api.life_api import register_life_api
    register_life_api(app, mongo_db=mongo_db)

    from app.api.onboarding_api import register_onboarding_api
    register_onboarding_api(app)

    from app.api.subscriptions_api import register_subscriptions_api
    register_subscriptions_api(app)

    from app.api.social_auth_api import register_social_auth_api
    register_social_auth_api(app)

    # Langfuse stats for the /status frontend page.
    @app.route("/api/langfuse-stats", methods=["GET"])
    def langfuse_stats():
        import requests as _req
        from flask import jsonify as _json

        pub  = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
        sec  = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
        host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com").strip()

        if not pub or not sec:
            return _json({"configured": False}), 200

        auth = (pub, sec)
        base = host.rstrip("/")

        try:
            # Daily metrics: token counts and cost.
            daily = _req.get(
                f"{base}/api/public/metrics/daily",
                params={"days": 1},
                auth=auth, timeout=6,
            )
            daily_data = daily.json() if daily.ok else {}

            # Recent traces: count and average latency.
            traces_r = _req.get(
                f"{base}/api/public/traces",
                params={"limit": 50, "page": 1},
                auth=auth, timeout=6,
            )
            traces_data = traces_r.json() if traces_r.ok else {}

        except Exception as exc:
            return _json({"configured": True, "error": str(exc)}), 200

        traces = traces_data.get("data", [])
        latencies = [
            t.get("latency") for t in traces if t.get("latency") is not None
        ]
        avg_latency = round(sum(latencies) / len(latencies)) if latencies else None

        # daily_data shape: {"data": [{"date":"...", "countTraces":N, "totalCost":F, ...}]}
        today = (daily_data.get("data") or [{}])[0]

        return _json({
            "configured": True,
            "traces_today":  today.get("countTraces", 0),
            "tokens_today":  today.get("totalTokens") or today.get("inputTokens", 0),
            "cost_today_usd": today.get("totalCost", 0),
            "avg_latency_ms": avg_latency,
            "total_traces":  traces_data.get("meta", {}).get("totalItems", len(traces)),
        }), 200

    # Auth endpoints
    @app.route("/api/auth", methods=["POST"])
    def web_auth():
        body = request.get_json(silent=True) or {}
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
        allowed, remaining = check_rate_limit(ip)
        if not allowed:
            return jsonify({"error": "too_many_attempts"}), 429
        password = (body.get("password") or "").strip()
        if not password or not check_owner_password(password):
            return jsonify({"error": "invalid_password", "remaining": remaining - 1}), 401
        # The owner's existing data (memory, tasks, reminders) lives under the
        # canonical Telegram id (SANDY_USER_CHAT_ID). Scope the app/web owner to
        # THAT id so the iPhone app is the SAME Sandy as Telegram — not a fresh,
        # empty owner bucket. (A minted owner_uid would be a separate scope.)
        from app.config import SANDY_USER_CHAT_ID
        owner_uid = str(SANDY_USER_CHAT_ID)
        try:
            token = make_token("owner", user_id=owner_uid)
        except RuntimeError:
            return jsonify({"error": "auth_not_configured"}), 503
        return jsonify({"token": token, "role": "owner", "user_id": owner_uid}), 200

    @app.route("/api/access/request", methods=["POST"])
    def web_access_request():
        body = request.get_json(silent=True) or {}
        name = (body.get("name") or "زاير").strip()[:50]
        reason = (body.get("reason") or "").strip()[:200]
        request_id = store_access_request(name, reason)
        return jsonify({"request_id": request_id}), 200

    @app.route("/api/access/status/<request_id>", methods=["GET"])
    def web_access_status(request_id):
        data = get_access_request(request_id)
        if not data:
            return jsonify({"status": "expired"}), 404
        resp = {"status": data["status"]}
        if data["status"] == "approved":
            resp["token"] = data["token"]
            resp["role"] = "guest"
        return jsonify(resp), 200

    # Web chat history (MongoDB)
    def _chat_history_key(claims):
        from app.config import SANDY_USER_CHAT_ID
        if claims.get("role") == "owner":
            return f"web_chat_{SANDY_USER_CHAT_ID}"
        return f"web_chat_{claims.get('jti', 'guest')}"

    @app.route("/api/chat/history", methods=["GET"])
    @require_auth
    def get_chat_history(claims):
        if mongo_db is None:
            return jsonify({"messages": []}), 200
        key = _chat_history_key(claims)
        doc = mongo_db.web_chat_history.find_one({"_id": key}, {"_id": 0, "messages": 1})
        return jsonify({"messages": doc["messages"] if doc else []}), 200

    @app.route("/api/chat/history", methods=["PUT"])
    @require_auth
    def put_chat_history(claims):
        from datetime import timedelta
        if mongo_db is None:
            return jsonify({"ok": True}), 200
        body = request.get_json(silent=True) or {}
        messages = body.get("messages", [])
        key = _chat_history_key(claims)
        expire_at = None if claims.get("role") == "owner" else \
            datetime.now(timezone.utc) + timedelta(hours=48)
        doc = {"_id": key, "messages": messages, "updated_at": datetime.now(timezone.utc)}
        if expire_at:
            doc["expire_at"] = expire_at
        mongo_db.web_chat_history.replace_one({"_id": key}, doc, upsert=True)
        return jsonify({"ok": True}), 200

    # Web agent endpoint: full SA pipeline, shared memory.
    @app.route("/api/agent", methods=["POST"])
    @require_auth
    def web_agent(claims):
        from app.agent.graph.graph import run_graph, get_final_reply
        from app.config import SANDY_USER_CHAT_ID

        body = request.get_json(silent=True) or {}

        message = (body.get("message") or "").strip()
        if not message:
            return jsonify({"error": "no message"}), 400

        # Site language picks Sandy's reply language (same personality).
        lang = (body.get("lang") or "ar").strip().lower()

        role = claims.get("role", "guest")
        # Identity from the token: every authenticated user has a stable
        # user_id (minted in users_store). The owner is just user #1.
        user_id = claims.get("user_id") or str(SANDY_USER_CHAT_ID)

        # Cost control: meter every authenticated request per user. The owner is
        # exempt from rejection (limit 0) but still counted; subscribers get a
        # generous quota, free users a modest one. Guests use demo data — skip.
        if role != "guest":
            from app.features import users_store, usage_store
            if role == "owner":
                _daily, _per_min = 0, 0
            elif users_store.is_subscriber(user_id):
                _daily, _per_min = 5000, 60
            else:
                _daily, _per_min = 40, 12
            _over = usage_store.check_and_record(
                user_id, daily_limit=_daily, per_min_limit=_per_min
            )
            if _over:
                return jsonify({"error": _over}), 429

        # Authenticated users (owner + signed-in users) get the full per-user
        # pipeline; only true guests fall through to the basic demo chat.
        if role in ("owner", "user"):
            try:
                import base64
                from app.utils.user_profiles import (
                    active_user_profile_context,
                    build_user_profile,
                )
                # The active profile scopes data to this user. The owner gets
                # full permissions; a regular user gets self-only, so owner-only
                # tools still refuse while their own data works.
                _profile = build_user_profile(claims)
                graph_message = message
                if lang == "en":
                    graph_message = (
                        f"{message}\n\n(Note: I'm on the English interface — please "
                        "reply in English, keeping your usual personality.)"
                    )
                with active_user_profile_context(_profile):
                    state = run_graph(
                        graph_message,
                        user_id=user_id,
                        chat_id=user_id,
                        source="web",
                    )
                reply = get_final_reply(state)
                chunks = reply.get("chunks") or [reply.get("text", "")]
                text = "\n".join(chunks)
                img_bytes = reply.get("image_bytes")
                if img_bytes:
                    b64 = base64.b64encode(img_bytes).decode()
                    caption = reply.get("caption") or text
                    return jsonify({
                        "reply": caption,
                        "image_url": f"data:image/png;base64,{b64}",
                        "role": role,
                    }), 200
                return jsonify({"reply": text, "role": role}), 200
            except Exception as exc:
                logger.exception("[web_agent] user pipeline failed")
                log_unhandled_exception(mongo_db, exc, source="web_agent")
                return jsonify({"error": "internal_error"}), 500

        # Guest path: rate-limit check, then a friendly basic chat.
        from app.agent.guest_usage import check_and_increment, guest_label
        jti = claims.get("jti", "")
        # One shared budget for guests across chat, search, voice and images.
        chat_type = "all"
        guest_name = claims.get("name") or (guest_label(jti) if jti else "زائر")
        status, count, limit = check_and_increment(jti, guest_name, chat_type, mongo_db)
        if status == "pending":
            return jsonify({
                "error": "limit_reached",
                "message": f"وصلت للحد المسموح ({limit} {chat_type}). طلبت الإذن من المسؤول — انتظر الموافقة.",
                "count": count, "limit": limit,
            }), 429
        if status == "block":
            return jsonify({
                "error": "access_denied",
                "message": "تم رفض طلبك من المسؤول.",
                "count": count, "limit": limit,
            }), 403

        try:
            from app.config import GUEST_PERSONALITY
            from app.agent.facade.agent import create_chat_completion
            history = body.get("history") or []
            guest_system = GUEST_PERSONALITY
            if lang == "en":
                guest_system += (
                    " IMPORTANT: The user is on the English interface — reply in natural, "
                    "fluent English while keeping the same warm, friendly personality "
                    "(you can still say you're Sandy, built by Nabeel)."
                )
            messages = [{"role": "system", "content": guest_system}]
            for h in history[-6:]:
                r = "user" if h.get("role") == "user" else "assistant"
                messages.append({"role": r, "content": h.get("text", "")})
            messages.append({"role": "user", "content": message})
            # Route through the shared chat-completion helper so guest chat gets
            # the same circuit breaker + timeouts as the rest of the pipeline.
            resp = create_chat_completion(messages=messages, max_tokens=300)
            return jsonify({"reply": resp.choices[0].message.content, "role": "guest"}), 200
        except Exception as exc:
            logger.exception("[web_agent] guest chat failed")
            log_unhandled_exception(mongo_db, exc, source="web_agent_guest")
            return jsonify({"error": "internal_error"}), 500

    @app.route("/api/image", methods=["POST"])
    @require_auth
    def web_image(claims):
        body = request.get_json(silent=True) or {}

        prompt = (body.get("prompt") or "").strip()
        if not prompt:
            return jsonify({"error": "no prompt"}), 400

        # Rate-limit guests on image generation
        if claims.get("role") != "owner":
            from app.agent.guest_usage import check_and_increment, guest_label
            jti = claims.get("jti", "")
            guest_name = claims.get("name") or (guest_label(jti) if jti else "زائر")
            status, count, limit = check_and_increment(jti, guest_name, "all", mongo_db)
            if status == "pending":
                return jsonify({
                    "error": "limit_reached",
                    "message": f"وصلت للحد المسموح ({limit}). طلبت الإذن من المسؤول — انتظر الموافقة.",
                    "count": count, "limit": limit,
                }), 429
            if status == "block":
                return jsonify({
                    "error": "access_denied",
                    "message": "تم رفض طلبك من المسؤول.",
                }), 403

        try:
            import base64
            from app.features.vision import generate_image_with_azure
            img_bytes = generate_image_with_azure(prompt)
            if img_bytes:
                b64 = base64.b64encode(img_bytes).decode()
                return jsonify({"url": f"data:image/png;base64,{b64}"}), 200
            return jsonify({"error": "تعذّر توليد الصورة"}), 500
        except Exception as exc:
            logger.exception("[web_image] image generation failed")
            log_unhandled_exception(mongo_db, exc, source="web_image")
            return jsonify({"error": "internal_error"}), 500

    @app.route("/api/guest-usage/status", methods=["GET"])
    @require_auth
    def guest_usage_status(claims):
        """Read-only poll so the web UI can tell a guest when the owner
        approved or rejected their pending request. Does NOT consume usage."""
        from app.agent.guest_usage import get_usage_doc
        if claims.get("role") == "owner":
            return jsonify({"state": "approved", "count": 0, "limit": 0}), 200
        # unified budget → always read the shared "all" doc, whatever type the UI polls
        jti = claims.get("jti", "")
        doc = get_usage_doc(jti, "all", mongo_db) or {}
        return jsonify({
            "state": doc.get("approval_state", "none"),
            "count": doc.get("count", 0),
            "limit": doc.get("limit", 3),
        }), 200

    @app.route("/api/analyze-image", methods=["POST"])
    @require_auth
    def web_analyze_image(claims):
        """Analyze an image (base64) via Azure Vision and return Sandy's description."""
        body = request.get_json(silent=True) or {}

        image_b64 = (body.get("image") or "").strip()
        question = (body.get("question") or "صف هذه الصورة بتفصيل").strip()
        if (body.get("lang") or "ar").strip().lower() == "en":
            question = f"{question}\n\n(Reply in English.)"
        if not image_b64:
            return jsonify({"error": "no image"}), 400

        # Rate-limit guests (shared unified budget)
        if claims.get("role") != "owner":
            from app.agent.guest_usage import check_and_increment, guest_label
            jti = claims.get("jti", "")
            guest_name = claims.get("name") or (guest_label(jti) if jti else "زائر")
            status, count, limit = check_and_increment(jti, guest_name, "all", mongo_db)
            if status == "pending":
                return jsonify({
                    "error": "limit_reached",
                    "message": f"وصلت للحد المسموح ({limit}). طُلب الإذن من المسؤول.",
                    "count": count, "limit": limit,
                }), 429
            if status == "block":
                return jsonify({"error": "access_denied", "message": "تم رفض طلبك."}), 403

        try:
            import base64 as _b64
            from app.features.vision import analyze_image_with_azure
            # analyze_image_with_azure needs the bound chat-completion fn (the
            # one with the Azure/OpenAI clients and circuit breaker) that the
            # Telegram pipeline uses. Without it the call raised TypeError and
            # every web image analysis failed.
            from app.agent.facade.agent import create_chat_completion
            img_bytes = _b64.b64decode(image_b64)
            reply = analyze_image_with_azure(
                img_bytes, question, create_chat_completion_fn=create_chat_completion
            )
            return jsonify({"reply": reply or "تعذّر تحليل الصورة"}), 200
        except Exception as exc:
            logger.exception("[web_analyze_image] image analysis failed")
            log_unhandled_exception(mongo_db, exc, source="web_analyze_image")
            return jsonify({"error": "internal_error"}), 500

    @app.route('/')
    def index():
        from flask import redirect
        frontend = os.getenv('FRONTEND_URL', '').rstrip('/')
        if frontend:
            return redirect(frontend)
        return jsonify({'status': 'Sandy API running'}), 200

    return app


