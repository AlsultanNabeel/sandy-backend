import logging
import os
from datetime import datetime, timezone

from flask import Flask, jsonify, request, Response
from flask_cors import CORS

from app.agent.semantic_memory import semantic_memory_stats

logger = logging.getLogger(__name__)

# سقف طول الرسالة النصية قبل أي استدعاء نموذج — يمنع انفجار التوكنات/الكلفة.
# (حجم جسم الطلب ككل مسقوف بـ MAX_CONTENT_LENGTH داخل create_app.)
_MAX_MESSAGE_CHARS = 6000


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
    # سقف حجم جسم الطلب (١٦ ميغابايت): يسمح بصور base64 المعقولة ويرفض
    # الأجسام الضخمة مبكراً (413) قبل ما تُقرأ للذاكرة — حاجز إغراق.
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
    from app.config import APP_ENV  # already defined in config.py
    _frontend = os.getenv("FRONTEND_URL", "").strip()
    if _frontend:
        _cors_origins = _frontend
    elif APP_ENV != "prod":
        _cors_origins = "*"            # dev convenience only
    else:
        logger.error("[server] FRONTEND_URL not set in prod; CORS restricted to same-origin")
        _cors_origins = []             # deny cross-origin rather than allow all
    CORS(app, resources={r"/api/*": {"origins": _cors_origins}})

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

    from app.api.voice_ws import register_voice_ws
    register_voice_ws(app)

    from app.api.voice_api import register_voice_api
    register_voice_api(app)

    from app.api.productivity_api import register_productivity_api
    register_productivity_api(app, mongo_db=mongo_db)

    from app.api.studio_api import register_studio_api
    register_studio_api(app, mongo_db=mongo_db)

    from app.api.research_api import register_research_api
    register_research_api(app)

    from app.api.conversations_api import register_conversations_api
    register_conversations_api(app, mongo_db=mongo_db)

    from app.api.memory_api import register_memory_api
    register_memory_api(app, mongo_db=mongo_db)

    from app.api.timeline_api import register_timeline_api
    register_timeline_api(app)

    from app.api.life_api import register_life_api
    register_life_api(app, mongo_db=mongo_db)

    from app.api.devices_api import register_devices_api
    register_devices_api(app, mongo_db=mongo_db)

    from app.api.onboarding_api import register_onboarding_api
    register_onboarding_api(app)

    from app.api.daily_nudge_api import register_daily_nudge_api
    register_daily_nudge_api(app, mongo_db=mongo_db)

    from app.api.push_api import register_push_api
    register_push_api(app)

    from app.api.features_api import register_features_api
    register_features_api(app)

    from app.api.persona_api import register_persona_api
    register_persona_api(app)

    from app.api.subscriptions_api import register_subscriptions_api
    register_subscriptions_api(app)

    from app.api.social_auth_api import register_social_auth_api
    register_social_auth_api(app)

    from app.api.email_auth_api import register_email_auth_api
    register_email_auth_api(app)

    from app.api.goals_api import register_goals_api
    register_goals_api(app, mongo_db=mongo_db)

    from app.api.future_messages_api import register_future_messages_api
    register_future_messages_api(app, mongo_db=mongo_db)

    from app.api.photos_api import register_photos_api
    register_photos_api(app, mongo_db=mongo_db)

    from app.api.gifts_api import register_gifts_api
    register_gifts_api(app, mongo_db=mongo_db)

    from app.api.share_api import register_share_api
    register_share_api(app, mongo_db=mongo_db)

    from app.api.weather_api import register_weather_api
    register_weather_api(app, mongo_db=mongo_db)

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
        # The owner is tenant #1: log him in under his clean sandy_users uuid
        # (provider="owner") — the id Phase 1 migrated his data onto — not the
        # legacy Telegram id. get_or_create_owner() is idempotent and returns
        # that stable uuid; fall back to SANDY_USER_CHAT_ID only if Mongo is down.
        from app.config import SANDY_USER_CHAT_ID
        from app.features import users_store
        owner_uid = users_store.get_or_create_owner() or str(SANDY_USER_CHAT_ID)
        try:
            token = make_token("owner", user_id=owner_uid)
        except RuntimeError:
            return jsonify({"error": "auth_not_configured"}), 503
        return jsonify({"token": token, "role": "owner", "user_id": owner_uid}), 200

    @app.route("/api/access/request", methods=["POST"])
    def web_access_request():
        # حدّ معدّل بالأيبي: يمنع إغراق المالك بطلبات وصول وهمية وملء sandy_auth.
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
        allowed, _ = check_rate_limit(ip, scope="access")
        if not allowed:
            return jsonify({"error": "too_many_attempts"}), 429
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
        # Authenticated users (owner + signed-in) key history by their stable
        # user_id; only guests fall back to the per-token jti.
        if claims.get("role") != "guest":
            return f"web_chat_{claims.get('user_id', '')}"
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
        expire_at = None if claims.get("role") != "guest" else \
            datetime.now(timezone.utc) + timedelta(hours=48)
        doc = {"_id": key, "messages": messages, "updated_at": datetime.now(timezone.utc)}
        if expire_at:
            doc["expire_at"] = expire_at
        mongo_db.web_chat_history.replace_one({"_id": key}, doc, upsert=True)
        return jsonify({"ok": True}), 200

    # Web agent endpoint: full SA pipeline, shared memory.
    def _run_authenticated_agent(claims: dict, body: dict, lang: str) -> dict:
        """The full per-user LangGraph pipeline for an owner/user request:
        builds the profile, runs the graph, saves pending state, formats the
        reply. Synchronous — shared by ``/api/agent`` (calls it directly) and
        ``/api/agent/stream`` (calls it inside a worker thread, with stream
        hooks set just before the call in that same thread), so the two
        routes can't drift on metering/graph logic. Raises on failure; the
        caller decides how to report it (JSON error vs. an SSE error event).
        """
        from app.agent.graph.graph import run_graph, get_final_reply
        from app.agent.pending_store import load_pending_state, save_pending_state
        from app.utils.user_profiles import active_user_profile_context, build_user_profile

        user_id = claims.get("user_id") or ""
        role = claims.get("role", "guest")
        message = (body.get("message") or "").strip()[:_MAX_MESSAGE_CHARS]

        # The active profile scopes data to THIS user via current_user_id().
        # Every authenticated user (owner included) gets full CRUD on their
        # own data; isolation is by scope.
        _profile = build_user_profile(claims)
        graph_message = message
        if lang == "en":
            graph_message = (
                f"{message}\n\n(Note: I'm on the English interface — please "
                "reply in English, keeping your usual personality.)"
            )
        # سيشن الشات (اختياري): يفصل ذاكرة كل محادثة على حدة. غيابه =
        # السلوك القديم (خيط واحد لكل مستخدم).
        conversation_id = (body.get("conversation_id") or "").strip()
        # نفس مفتاح الخيط اللي run_graph نفسه بيستخدمه (thread_id) —
        # لازم يتطابق تماماً عشان الـ pending يتحمّل ويترجع لنفس المحادثة.
        thread_id = conversation_id or user_id
        loaded_pending = load_pending_state(thread_id, user_id, mongo_db)
        with active_user_profile_context(_profile):
            state = run_graph(
                graph_message,
                user_id=user_id,
                chat_id=user_id,
                source="web",
                conversation_id=conversation_id or None,
                pending_state=loaded_pending,
            )
        save_pending_state(thread_id, user_id, mongo_db, state.get("pending_state"))
        reply = get_final_reply(state)
        chunks = reply.get("chunks") or [reply.get("text", "")]
        text = "\n".join(chunks)
        result = {"reply": text, "role": role}
        img_bytes = reply.get("image_bytes")
        if img_bytes:
            import base64
            b64 = base64.b64encode(img_bytes).decode()
            result["reply"] = reply.get("caption") or text
            result["image_url"] = f"data:image/png;base64,{b64}"
        return result

    @app.route("/api/agent", methods=["POST"])
    @require_auth
    def web_agent(claims):
        body = request.get_json(silent=True) or {}

        message = (body.get("message") or "").strip()[:_MAX_MESSAGE_CHARS]
        if not message:
            return jsonify({"error": "no message"}), 400

        # Site language picks Sandy's reply language (same personality).
        lang = (body.get("lang") or "ar").strip().lower()

        role = claims.get("role", "guest")
        # Identity from the token: every authenticated user has a stable
        # user_id (minted in users_store). The owner is just user #1 — no
        # owner-id fallback, so a token without a user_id gets an empty scope.
        user_id = claims.get("user_id") or ""

        # Cost control: meter every authenticated request per user. The owner is
        # tenant #1 / operator, so he shares the top (subscriber) tier; free
        # users get a modest quota. Guests use demo data — skip.
        if role != "guest":
            from app.features import users_store, usage_store
            if role == "owner" or users_store.is_subscriber(user_id):
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
                return jsonify(_run_authenticated_agent(claims, body, lang)), 200
            except Exception:
                logger.exception("[web_agent] user pipeline failed")
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
        except Exception:
            logger.exception("[web_agent] guest chat failed")
            return jsonify({"error": "internal_error"}), 500

    @app.route("/api/agent/stream", methods=["POST"])
    @require_auth
    def web_agent_stream(claims):
        """Same pipeline as /api/agent, but streams the chat_respond LLM
        reply token-by-token over SSE as it's generated, so the app can show
        text arriving instead of waiting for the full reply. Only helps the
        plain-chat path (routing + tool actions like adding a task still run
        to completion before anything streams — there's no partial output to
        show there). Owner/signed-in users only; guests use plain /api/agent.
        """
        import json
        import queue
        import threading

        from app.agent.nodes.execute import clear_stream_hooks, set_stream_hooks

        body = request.get_json(silent=True) or {}
        message = (body.get("message") or "").strip()[:_MAX_MESSAGE_CHARS]
        if not message:
            return jsonify({"error": "no message"}), 400

        lang = (body.get("lang") or "ar").strip().lower()
        role = claims.get("role", "guest")
        user_id = claims.get("user_id") or ""

        if role not in ("owner", "user"):
            return jsonify({"error": "streaming_requires_account"}), 403

        from app.features import users_store, usage_store
        if role == "owner" or users_store.is_subscriber(user_id):
            _daily, _per_min = 5000, 60
        else:
            _daily, _per_min = 40, 12
        _over = usage_store.check_and_record(
            user_id, daily_limit=_daily, per_min_limit=_per_min
        )
        if _over:
            return jsonify({"error": _over}), 429

        chunk_queue: "queue.Queue" = queue.Queue()
        outcome: dict = {}

        def _worker():
            # Hooks + active profile are thread-local — both must be set
            # HERE, inside the worker thread, not the request thread that
            # spawned it (they don't cross threads).
            set_stream_hooks(on_start=lambda: None, on_chunk=chunk_queue.put)
            try:
                outcome["result"] = _run_authenticated_agent(claims, body, lang)
            except Exception:
                logger.exception("[web_agent_stream] user pipeline failed")
                outcome["error"] = True
            finally:
                clear_stream_hooks()
                chunk_queue.put(None)  # sentinel: no more chunks

        threading.Thread(target=_worker, daemon=True).start()

        def _generate():
            while True:
                try:
                    item = chunk_queue.get(timeout=10)
                except queue.Empty:
                    # No chunk yet (routing/tool call still running). Emit an SSE
                    # comment so Heroku's router sees the request is alive and
                    # doesn't kill a slow-but-working turn (H12 at ~30s of silence).
                    yield ": keep-alive\n\n"
                    continue
                if item is None:
                    break
                yield f"data: {json.dumps({'text': item}, ensure_ascii=False)}\n\n"

            if outcome.get("error"):
                yield f"data: {json.dumps({'error': 'internal_error'})}\n\n"
                return

            payload = dict(outcome.get("result") or {})
            payload["done"] = True
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        return Response(
            _generate(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.route("/api/image", methods=["POST"])
    @require_auth
    def web_image(claims):
        body = request.get_json(silent=True) or {}

        prompt = (body.get("prompt") or "").strip()
        if not prompt:
            return jsonify({"error": "no prompt"}), 400

        # Rate-limit guests on image generation (authenticated users are metered
        # in /api/agent instead, not via the visitor-approval flow).
        if claims.get("role") == "guest":
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
        except Exception:
            logger.exception("[web_image] image generation failed")
            return jsonify({"error": "internal_error"}), 500

    @app.route("/api/image/edit", methods=["POST"])
    @require_auth
    def web_image_edit(claims):
        body = request.get_json(silent=True) or {}

        prompt = (body.get("prompt") or "").strip()
        image_b64 = (body.get("image") or "").strip()
        if not prompt or not image_b64:
            return jsonify({"error": "no prompt or image"}), 400

        # Same guest metering as /api/image (authenticated users metered in /api/agent).
        if claims.get("role") == "guest":
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
            from app.features.vision import edit_image_with_azure
            img_bytes = edit_image_with_azure(base64.b64decode(image_b64), prompt)
            if img_bytes:
                b64 = base64.b64encode(img_bytes).decode()
                return jsonify({"url": f"data:image/png;base64,{b64}"}), 200
            return jsonify({"error": "تعذّر تعديل الصورة"}), 500
        except Exception:
            logger.exception("[web_image_edit] image edit failed")
            return jsonify({"error": "internal_error"}), 500

    @app.route("/api/guest-usage/status", methods=["GET"])
    @require_auth
    def guest_usage_status(claims):
        """Read-only poll so the web UI can tell a guest when the owner
        approved or rejected their pending request. Does NOT consume usage."""
        from app.agent.guest_usage import get_usage_doc
        if claims.get("role") != "guest":
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

        # Rate-limit guests (shared unified budget). Authenticated users are
        # metered in /api/agent, not via the visitor-approval flow.
        if claims.get("role") == "guest":
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
                img_bytes, question, create_chat_completion_fn=create_chat_completion,
                user_id=claims.get("user_id") or None,
            )
            return jsonify({"reply": reply or "تعذّر تحليل الصورة"}), 200
        except Exception:
            logger.exception("[web_analyze_image] image analysis failed")
            return jsonify({"error": "internal_error"}), 500

    @app.route('/')
    def index():
        from flask import redirect
        frontend = os.getenv('FRONTEND_URL', '').rstrip('/')
        if frontend:
            return redirect(frontend)
        return jsonify({'status': 'Sandy API running'}), 200

    return app


