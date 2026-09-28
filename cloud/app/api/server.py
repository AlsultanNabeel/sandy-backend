"""Flask app factory: health, chat/agent (plain + SSE), image routes, and every API module."""

import base64
import json
import logging
import os
import queue
import threading
import time
from datetime import datetime, timedelta, timezone

from flask import Flask, jsonify, request, Response
from flask_cors import CORS

from app.agent.semantic_memory import semantic_memory_stats

logger = logging.getLogger(__name__)


# سقف طول الرسالة النصية قبل أي استدعاء نموذج (كلفة/توكنات).
_MAX_MESSAGE_CHARS = 6000

# سقف جسم الطلب: يرفض الأجسام الضخمة (413) قبل ما تنقرا للذاكرة.
_MAX_CONTENT_LENGTH = 16 * 1024 * 1024

# سقف وصف الصورة: نرفض هون مجّاناً بدل ما ندفع نداء المزوّد بيرفضه.
_MAX_IMAGE_PROMPT_CHARS = 2000


# أقصى عدد رسائل بنحفظه من سجل شات الويب (الأحدث).
_MAX_HISTORY_MESSAGES = 500

# مدة بقاء سجل شات الزائر قبل انتهائه (٤٨ ساعة).
_GUEST_CHAT_TTL = timedelta(hours=48)

# A retried send whose first run is still going waits this long on the stream route.
_DUPLICATE_WAIT_S = 120
_STILL_PROCESSING = {
    "error": "still_processing",
    "message": "ساندي لسا عم تجاوب على هالرسالة، لحظة.",
}


def create_app(
    *,
    mongo_db=None,
    semantic_memory_stats_fn=semantic_memory_stats,
):
    # Imported here so importing this module doesn't need PyJWT.
    from app.api.auth_handlers import require_auth

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = _MAX_CONTENT_LENGTH
    from app.config import APP_ENV, RELEASE_ID
    _frontend = os.getenv("FRONTEND_URL", "").strip()
    if _frontend:
        _cors_origins = _frontend
    elif APP_ENV != "prod":
        _cors_origins = "*"            # dev only
    else:
        logger.error("[server] FRONTEND_URL not set in prod; CORS restricted to same-origin")
        _cors_origins = []
    CORS(app, resources={r"/api/*": {"origins": _cors_origins}})

    # Typed errors (app.errors.SandyError) become {"error": <code>} with their status.
    from app.errors import SandyError

    @app.errorhandler(SandyError)
    def _handle_sandy_error(err: SandyError):
        if err.http_status >= 500:
            logger.error("[api] %s: %s", err.code, err)
        return jsonify({"error": err.code}), err.http_status

    @app.route("/health", methods=["GET"])
    def health():
        mongo_status = {"ok": False, "available": mongo_db is not None}
        if mongo_db is not None:
            try:
                mongo_db.command("ping")
                mongo_status.update(
                    {"ok": True, "database": getattr(mongo_db, "name", None)}
                )
            except Exception as exc:  # noqa: BLE001 — a health probe reports, never raises
                # Type only: this endpoint is public and driver errors name the host.
                logger.warning("[health] mongo ping failed: %s", exc)
                mongo_status["error"] = type(exc).__name__

        chroma_status = {"ok": False}
        try:
            chroma_data = semantic_memory_stats_fn() if callable(semantic_memory_stats_fn) else {}
            chroma_status.update({"ok": True, **(chroma_data or {})})
        except Exception as exc:  # noqa: BLE001
            logger.warning("[health] semantic memory stats failed: %s", exc)
            chroma_status["error"] = type(exc).__name__

        overall_ok = (
            mongo_status.get("ok")
            and chroma_status.get("ok")
        )
        return jsonify(
            {
                "ok": bool(overall_ok),
                # Which build is serving.
                "release": RELEASE_ID,
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

    from app.api.insights_api import register_insights_api
    register_insights_api(app, mongo_db=mongo_db)

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

    from app.api.account_api import register_account_api
    register_account_api(app)

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

    from app.api.firmware_api import register_firmware_api
    register_firmware_api(app)

    # Sign-in is Apple, Google or email (the shared owner-password /api/auth is gone).
    from app.api.metering import limit_response as _limit_response
    from app.api.metering import meter_or_error as _meter_or_error

    def _guest_media_gate(claims):
        """Charge one shared guest unit; a ready ``(body, status)`` refusal, or None."""
        if claims.get("role") != "guest":
            return None
        from app.agent.guest_usage import check_and_increment, guest_label

        jti = claims.get("jti", "")
        guest_name = claims.get("name") or (guest_label(jti) if jti else "زائر")
        status, count, limit = check_and_increment(jti, guest_name, "all", mongo_db)
        if status == "pending":
            return {
                "error": "limit_reached",
                "message": f"وصلت للحد المسموح ({limit}). طلبت الإذن من المسؤول — انتظر الموافقة.",
                "count": count,
                "limit": limit,
            }, 429
        if status == "block":
            return {
                "error": "access_denied",
                "message": "تم رفض طلبك من المسؤول.",
            }, 403
        return None

    def _media_gate(claims):
        """Meter one image-model call (guest budget or tier quota); a ``(body, status)`` refusal, or None."""
        if claims.get("role") == "guest":
            return _guest_media_gate(claims)
        over = _meter_or_error(claims.get("role", "user"), claims.get("user_id") or "")
        if over:
            return _limit_response(over), 429
        return None

    def _decode_image(image_b64: str):
        """Client base64 → bytes, or None (→ 400)."""
        import binascii

        try:
            return base64.b64decode(image_b64, validate=True)
        except (binascii.Error, ValueError):
            return None

    def _chat_history_key(claims):
        # Signed-in users key by user_id; guests by token jti.
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
        if mongo_db is None:
            return jsonify({"ok": True}), 200
        body = request.get_json(silent=True) or {}
        messages = body.get("messages", [])
        if not isinstance(messages, list):
            return jsonify({"error": "invalid_request"}), 400
        # Newest only: Mongo documents cap at 16 MB.
        messages = messages[-_MAX_HISTORY_MESSAGES:]
        key = _chat_history_key(claims)
        expire_at = None if claims.get("role") != "guest" else \
            datetime.now(timezone.utc) + _GUEST_CHAT_TTL
        doc = {"_id": key, "messages": messages, "updated_at": datetime.now(timezone.utc)}
        if expire_at:
            doc["expire_at"] = expire_at
        mongo_db.web_chat_history.replace_one({"_id": key}, doc, upsert=True)
        return jsonify({"ok": True}), 200

    def _run_authenticated_agent(claims: dict, body: dict) -> dict:
        """Run the per-user graph pipeline and format the reply.

        Shared by /api/agent and /api/agent/stream (inside its worker thread). Raises on failure.
        """
        from app.agent.graph.graph import run_graph, get_final_reply
        from app.agent.pending_store import load_pending_state, save_pending_state
        from app.utils.user_profiles import active_user_profile_context, build_user_profile

        user_id = claims.get("user_id") or ""
        role = claims.get("role", "guest")
        message = (body.get("message") or "").strip()[:_MAX_MESSAGE_CHARS]

        _profile = build_user_profile(claims)
        # Optional chat session: each conversation gets its own memory thread.
        conversation_id = (body.get("conversation_id") or "").strip()
        # Must match run_graph's thread_id so pending state round-trips.
        thread_id = conversation_id or user_id
        loaded_pending = load_pending_state(thread_id, user_id, mongo_db)
        with active_user_profile_context(_profile):
            state = run_graph(
                message,
                user_id=user_id,
                chat_id=user_id,
                source="web",
                conversation_id=conversation_id or None,
                pending_state=loaded_pending,
            )
        save_pending_state(thread_id, user_id, mongo_db, state.get("pending_state"))
        reply = get_final_reply(state)
        text = reply.get("text", "")
        result = {"reply": text, "role": role}
        img_bytes = reply.get("image_bytes")
        if img_bytes:
            b64 = base64.b64encode(img_bytes).decode()
            result["reply"] = reply.get("caption") or text
            result["image_url"] = f"data:image/png;base64,{b64}"
        return result

    from app.api.conversations_api import (claim_turn, ensure_conversation, finish_turn,
                                           release_turn, turn_status, valid_client_id)

    def _conversation_refusal(user_id: str, body: dict):
        """A named conversation must be the caller's; the first turn naming a new app-chosen id creates it."""
        cid = (body.get("conversation_id") or "").strip()
        if not cid or mongo_db is None:
            return None
        if ensure_conversation(mongo_db, user_id, cid):
            return None
        return jsonify({"error": "conversation_not_found"}), 404

    def _client_msg_id(body: dict) -> str:
        cmid = body.get("client_msg_id")
        return cmid if valid_client_id(cmid) else ""

    @app.route("/api/agent", methods=["POST"])
    @require_auth
    def web_agent(claims):
        body = request.get_json(silent=True) or {}

        message = (body.get("message") or "").strip()[:_MAX_MESSAGE_CHARS]
        if not message:
            return jsonify({"error": "no message"}), 400

        role = claims.get("role", "guest")
        user_id = claims.get("user_id") or ""

        # A retried send (same client_msg_id) is answered from the ledger, never re-run or re-metered.
        # Idempotency: a retried send (same client_msg_id) is answered from
        # the ledger — never run, never metered twice.
        cmid = ""
        if role in ("owner", "user"):
            refused = _conversation_refusal(user_id, body)
            if refused is not None:
                return refused
            cmid = _client_msg_id(body)
            if cmid:
                turn, cached = claim_turn(mongo_db, user_id, cmid)
                if turn == "done":
                    return jsonify(cached), 200
                if turn == "processing":
                    return jsonify(_STILL_PROCESSING), 409

        # Meter every authenticated request (owner shares the subscriber tier).
        if role != "guest":
            _over = _meter_or_error(role, user_id)
            if _over:
                if cmid:
                    release_turn(mongo_db, user_id, cmid)
                return jsonify(_limit_response(_over)), 429

        if role in ("owner", "user"):
            try:
                result = _run_authenticated_agent(claims, body)
            except Exception:
                logger.exception("[web_agent] user pipeline failed")
                if cmid:
                    finish_turn(mongo_db, user_id, cmid, error=True)
                return jsonify({"error": "internal_error"}), 500
            if cmid:
                finish_turn(mongo_db, user_id, cmid, result)
            return jsonify(result), 200

        # Guest path: shared visitor budget, then a basic chat.
        from app.agent.guest_usage import check_and_increment, guest_label
        jti = claims.get("jti", "")
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
            from app.agent.context_builder import LANGUAGE_RULE
            from app.agent.facade.agent import create_chat_completion
            history = body.get("history") or []
            # Same language rule as every other channel.
            guest_system = GUEST_PERSONALITY + LANGUAGE_RULE
            messages = [{"role": "system", "content": guest_system}]
            for h in history[-6:]:
                r = "user" if h.get("role") == "user" else "assistant"
                messages.append({"role": r, "content": h.get("text", "")})
            messages.append({"role": "user", "content": message})
            resp = create_chat_completion(messages=messages, max_tokens=300)
            return jsonify({"reply": resp.choices[0].message.content, "role": "guest"}), 200
        except Exception:
            logger.exception("[web_agent] guest chat failed")
            return jsonify({"error": "internal_error"}), 500

    @app.route("/api/agent/stream", methods=["POST"])
    @require_auth
    def web_agent_stream(claims):
        """/api/agent with the chat reply streamed token by token over SSE (accounts only)."""
        from app.agent.nodes.execute import clear_stream_hooks, set_stream_hooks

        body = request.get_json(silent=True) or {}
        message = (body.get("message") or "").strip()[:_MAX_MESSAGE_CHARS]
        if not message:
            return jsonify({"error": "no message"}), 400

        role = claims.get("role", "guest")
        user_id = claims.get("user_id") or ""

        if role not in ("owner", "user"):
            return jsonify({"error": "streaming_requires_account"}), 403

        refused = _conversation_refusal(user_id, body)
        if refused is not None:
            return refused

        sse_headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

        def _sse(obj) -> str:
            return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

        # A retry of a send the network cut: replay the stored reply, or wait for the running one.
        cmid = _client_msg_id(body)
        if cmid:
            turn, cached = claim_turn(mongo_db, user_id, cmid)
            if turn == "done":
                return Response(_sse({**cached, "done": True}),
                                mimetype="text/event-stream", headers=sse_headers)
            if turn == "processing":
                def _await_first_run():
                    deadline = time.monotonic() + _DUPLICATE_WAIT_S
                    last_ping = time.monotonic()
                    while time.monotonic() < deadline:
                        status, result = turn_status(mongo_db, user_id, cmid)
                        if status == "done":
                            yield _sse({**(result or {}), "done": True})
                            return
                        if status in ("error", "missing"):
                            yield _sse({"error": "internal_error"})
                            return
                        if time.monotonic() - last_ping >= 10:
                            last_ping = time.monotonic()
                            yield ": keep-alive\n\n"
                        time.sleep(0.5)
                    yield _sse(_STILL_PROCESSING)

                return Response(_await_first_run(), mimetype="text/event-stream",
                                headers=sse_headers)

        _over = _meter_or_error(role, user_id)
        if _over:
            if cmid:
                release_turn(mongo_db, user_id, cmid)
            return jsonify(_limit_response(_over)), 429

        chunk_queue: "queue.Queue" = queue.Queue()
        outcome: dict = {}

        def _worker():
            # Stream hooks and the profile are thread-local: set them in this thread.
            set_stream_hooks(on_start=lambda: None, on_chunk=chunk_queue.put)
            try:
                outcome["result"] = _run_authenticated_agent(claims, body)
                if cmid:
                    finish_turn(mongo_db, user_id, cmid, outcome["result"])
            except Exception:
                logger.exception("[web_agent_stream] user pipeline failed")
                outcome["error"] = True
                if cmid:
                    finish_turn(mongo_db, user_id, cmid, error=True)
            finally:
                clear_stream_hooks()
                chunk_queue.put(None)  # sentinel: no more chunks

        # Not fire-and-forget (C3b): the request waits on this thread, and a
        # shared-pool worker per stream would starve background work.
        threading.Thread(target=_worker, daemon=True).start()

        def _generate():
            while True:
                try:
                    item = chunk_queue.get(timeout=10)
                except queue.Empty:
                    # SSE comment so Heroku's router doesn't kill a slow turn (H12).
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
            yield _sse(payload)

        return Response(_generate(), mimetype="text/event-stream", headers=sse_headers)

    @app.route("/api/image", methods=["POST"])
    @require_auth
    def web_image(claims):
        body = request.get_json(silent=True) or {}

        prompt = (body.get("prompt") or "").strip()
        if not prompt:
            return jsonify({"error": "no prompt"}), 400
        if len(prompt) > _MAX_IMAGE_PROMPT_CHARS:
            return jsonify({"error": "prompt_too_long"}), 413

        gate = _media_gate(claims)
        if gate is not None:
            err_body, code = gate
            return jsonify(err_body), code

        try:
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
        if len(prompt) > _MAX_IMAGE_PROMPT_CHARS:
            return jsonify({"error": "prompt_too_long"}), 413

        gate = _media_gate(claims)
        if gate is not None:
            err_body, code = gate
            return jsonify(err_body), code

        source = _decode_image(image_b64)
        if source is None:
            return jsonify({"error": "invalid_image"}), 400
        try:
            from app.features.vision import edit_image_with_azure
            img_bytes = edit_image_with_azure(source, prompt)
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
        """Read-only poll of a guest's visitor budget (does not consume usage)."""
        from app.agent.guest_usage import get_usage_doc
        if claims.get("role") != "guest":
            return jsonify({"state": "approved", "count": 0, "limit": 0}), 200
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
        """Describe a base64 image in Sandy's voice."""
        body = request.get_json(silent=True) or {}

        image_b64 = (body.get("image") or "").strip()
        question = (body.get("question") or "صف هذه الصورة بتفصيل").strip()
        # لغة الردّ من السؤال نفسه، نفس القاعدة بكل القنوات.
        from app.agent.context_builder import LANGUAGE_RULE as _lang_rule
        question = f"{question}{_lang_rule}"
        if not image_b64:
            return jsonify({"error": "no image"}), 400

        gate = _media_gate(claims)
        if gate is not None:
            err_body, code = gate
            return jsonify(err_body), code

        try:
            from app.features.vision import analyze_image_with_azure
            from app.agent.facade.agent import create_chat_completion
            img_bytes = _decode_image(image_b64)
            if img_bytes is None:
                return jsonify({"error": "invalid_image"}), 400
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
