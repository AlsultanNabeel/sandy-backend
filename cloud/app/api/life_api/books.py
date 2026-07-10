"""حياتي API — books routes."""
from flask import jsonify, request

from app.api.auth_handlers import require_auth, require_tenant
from app.api.life_api._common import _DEMO, _is_guest
from app.utils.user_profiles import active_user_profile_context, build_user_profile


def _register_books(app):
    # ── القراءة ─────────────────────────────────────────────────────────
    @app.route("/api/life/books", methods=["GET"])
    @require_auth
    def api_books(claims):
        if _is_guest(claims):
            return jsonify({"items": _DEMO["books"], "demo": True, "stats": {"sessions": 4, "pages": 96, "minutes": 210}}), 200
        from app.features.reading_store import goal_progress, list_books, reading_stats

        with active_user_profile_context(build_user_profile(claims)):
            items = list_books()
            stats = reading_stats(days=30)
            goal = goal_progress()
        return jsonify({"items": items, "stats": stats, "goal": goal, "demo": False}), 200

    @app.route("/api/life/books", methods=["POST"])
    @require_tenant
    def api_books_add(claims):
        body = request.get_json(silent=True) or {}
        from app.features.reading_store import add_book

        r = add_book(
            (body.get("title") or "").strip(),
            status=(body.get("status") or "reading").strip(),
            total_pages=int(body.get("total_pages", 0) or 0),
            cover_url=(body.get("cover_url") or "").strip(),
            current_page=int(body.get("current_page", 0) or 0),
            author=(body.get("author") or "").strip(),
            category=(body.get("category") or "").strip(),
            fmt=(body.get("fmt") or "").strip(),
        )
        return jsonify(r), (200 if r.get("ok") else 400)

    @app.route("/api/life/books/status", methods=["POST"])
    @require_tenant
    def api_books_status(claims):
        body = request.get_json(silent=True) or {}
        from app.features.reading_store import set_book_status

        r = set_book_status(
            (body.get("title") or "").strip(), (body.get("status") or "").strip()
        )
        return jsonify(r), (200 if r.get("ok") else 404)

    @app.route("/api/life/books/detail", methods=["GET"])
    @require_tenant
    def api_book_detail(claims):
        from app.features.reading_store import get_book

        b = get_book((request.args.get("title") or "").strip())
        return jsonify(b or {"error": "not_found"}), (200 if b else 404)

    @app.route("/api/life/books/meta", methods=["POST"])
    @require_tenant
    def api_book_meta(claims):
        body = request.get_json(silent=True) or {}
        from app.features.reading_store import set_book_meta

        def _opt(k, cast=str):
            v = body.get(k)
            return cast(v) if v is not None and str(v) != "" else None

        r = set_book_meta(
            (body.get("title") or "").strip(),
            author=_opt("author"), category=_opt("category"),
            rating=_opt("rating", int), fmt=_opt("fmt"),
            total_pages=_opt("total_pages", int), current_page=_opt("current_page", int),
        )
        return jsonify(r), (200 if r.get("ok") else 404)

    @app.route("/api/life/books/note", methods=["POST"])
    @require_tenant
    def api_book_note(claims):
        body = request.get_json(silent=True) or {}
        from app.features.reading_store import add_note

        r = add_note((body.get("title") or "").strip(), (body.get("text") or "").strip())
        return jsonify(r), (200 if r.get("ok") else 400)

    @app.route("/api/life/books/quote", methods=["POST"])
    @require_tenant
    def api_book_quote(claims):
        body = request.get_json(silent=True) or {}
        from app.features.reading_store import add_quote

        r = add_quote((body.get("title") or "").strip(), (body.get("text") or "").strip(),
                      page=int(body.get("page", 0) or 0))
        return jsonify(r), (200 if r.get("ok") else 400)

    @app.route("/api/life/books/goal", methods=["POST"])
    @require_tenant
    def api_book_goal(claims):
        body = request.get_json(silent=True) or {}
        from app.features.reading_store import set_reading_goal

        r = set_reading_goal(
            books_year=int(body.get("books_year", 0) or 0),
            pages_year=int(body.get("pages_year", 0) or 0),
        )
        return jsonify(r), (200 if r.get("ok") else 400)
