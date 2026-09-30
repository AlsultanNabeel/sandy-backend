"""Photo album API over features/photo_album (bytes in GridFS, metadata in sandy_photos).

A tag is an album. Scoped to the caller; guests get nothing.

  GET /api/photos (?album= ?q=) · GET /api/photos/albums · GET /api/photos/<id>/file
  POST /api/photos (base64 image + optional name/album) · DELETE /api/photos/<id>
"""

from __future__ import annotations

import base64
import logging

from flask import Response, jsonify, request

from app.api.auth_handlers import require_auth, require_tenant
from app.utils.user_profiles import (
    active_user_profile_context,
    build_user_profile,
    current_user_id,
)

logger = logging.getLogger(__name__)

# Same GridFS bucket as photo_album; by-id routes read it directly.
_FILES_COLLECTION = "sandy_photo_files"

# سقف الرفع (8 ميغا): حد الطلب العام 16 ميغا كبير لهالمسار مع 16 طلب متوازي.
_MAX_PHOTO_BYTES = 8 * 1024 * 1024
# نفس السقف بحروف base64، بنقيسه قبل الفكّ عشان ما نخصّص الذاكرة.
_MAX_PHOTO_B64_CHARS = (_MAX_PHOTO_BYTES // 3 + 1) * 4


def _is_guest(claims) -> bool:
    return claims.get("role") == "guest"


def _gridfs(mongo_db):
    from gridfs import GridFS

    return GridFS(mongo_db, collection=_FILES_COLLECTION)


def _read_bytes(mongo_db, grid_id):
    try:
        return _gridfs(mongo_db).get(grid_id).read()
    except Exception as e:  # noqa: BLE001
        logger.warning("[photos_api] gridfs read failed: %s", e)
        return None


def _delete_bytes(mongo_db, grid_id) -> None:
    try:
        _gridfs(mongo_db).delete(grid_id)
    except Exception as e:  # noqa: BLE001
        logger.debug("[photos_api] gridfs delete: %s", e)


def _serialize(doc) -> dict:
    return {
        "id": str(doc.get("_id", "")),
        "name": (doc.get("name") or "").strip(),
        "caption": (doc.get("ai_caption") or doc.get("user_caption") or "").strip(),
        "tags": [t for t in (doc.get("tags") or []) if t],
        "created_at": doc.get("created_at") or "",
    }


def register_photos_api(app, mongo_db=None):
    from app.features import photo_album

    # Prime the album store in case the agent facade hasn't yet (idempotent).
    if mongo_db is not None and not photo_album.is_available():
        photo_album.init_photo_album(mongo_db)

    @app.route("/api/photos", methods=["GET"])
    @require_auth
    def get_photos(claims):
        if _is_guest(claims):
            return jsonify({"items": []}), 200
        album = (request.args.get("album") or "").strip() or None
        query = (request.args.get("q") or "").strip() or None
        with active_user_profile_context(build_user_profile(claims)):
            uid = current_user_id()
            if not uid:
                return jsonify({"items": []}), 200
            docs = photo_album.find_photos(uid, query=query, tag=album, limit=200)
        return jsonify({"items": [_serialize(d) for d in docs]}), 200

    @app.route("/api/photos/albums", methods=["GET"])
    @require_auth
    def get_albums(claims):
        """Distinct tags for this user with photo counts."""
        if _is_guest(claims):
            return jsonify({"items": []}), 200
        with active_user_profile_context(build_user_profile(claims)):
            uid = current_user_id()
            if not uid:
                return jsonify({"items": []}), 200
            counts = photo_album.tag_counts(uid)
        items = [
            {"name": name, "count": counts[name]}
            for name in sorted(counts, key=lambda n: (-counts[n], n))
        ]
        return jsonify({"items": items}), 200

    @app.route("/api/photos/<photo_id>/file", methods=["GET"])
    @require_auth
    def get_photo_file(claims, photo_id):
        """Stream one photo's bytes; the lookup only matches this user's photos."""
        if _is_guest(claims) or mongo_db is None:
            return jsonify({"error": "not_found"}), 404
        from bson import ObjectId
        from bson.errors import InvalidId

        try:
            oid = ObjectId(photo_id)
        except (InvalidId, TypeError):
            return jsonify({"error": "not_found"}), 404
        with active_user_profile_context(build_user_profile(claims)):
            uid = current_user_id()
            if not uid:
                return jsonify({"error": "not_found"}), 404
            doc = mongo_db["sandy_photos"].find_one({"_id": oid, "chat_id": uid})
            if not doc or doc.get("grid_id") is None:
                return jsonify({"error": "not_found"}), 404
            data = _read_bytes(mongo_db, doc["grid_id"])
        if not data:
            return jsonify({"error": "not_found"}), 404
        return Response(data, mimetype="image/jpeg")

    @app.route("/api/photos", methods=["POST"])
    @require_tenant
    def add_photo(claims):
        """Add a base64 photo (or data URI); caption/tags are generated in the background."""
        body = request.get_json(silent=True) or {}
        image_b64 = (body.get("image") or "").strip()
        if not image_b64:
            return jsonify({"error": "image_required"}), 400
        if "," in image_b64 and image_b64.lstrip().startswith("data:"):
            image_b64 = image_b64.split(",", 1)[1]
        if len(image_b64) > _MAX_PHOTO_B64_CHARS:
            logger.warning("[photos_api] upload rejected: %s base64 chars is too big",
                           len(image_b64))
            return jsonify({"error": "image_too_large"}), 413
        try:
            image_bytes = base64.b64decode(image_b64, validate=True)
        except (ValueError, TypeError):
            return jsonify({"error": "bad_image"}), 400
        if not image_bytes:
            return jsonify({"error": "bad_image"}), 400
        if len(image_bytes) > _MAX_PHOTO_BYTES:
            # Whitespace can slip past the character check.
            return jsonify({"error": "image_too_large"}), 413

        name = (body.get("name") or "").strip() or None
        album = (body.get("album") or "").strip()

        uid = current_user_id()
        if not uid:
            return jsonify({"error": "forbidden"}), 403
        from app.api.metering import meter_claims
        refusal = meter_claims(claims)
        if refusal:
            return jsonify(refusal[0]), refusal[1]
        saved = photo_album.save_photo(
            uid, image_bytes, name=name, user_caption=name or ""
        )
        if not saved:
            return jsonify({"error": "save_failed"}), 500

        photo_id = saved["_id"]
        _start_ai_tagging(photo_id, image_bytes, album)
        return jsonify({"ok": True, "id": str(photo_id)}), 200

    @app.route("/api/photos/<photo_id>", methods=["DELETE"])
    @require_auth
    def delete_photo(claims, photo_id):
        if _is_guest(claims) or mongo_db is None:
            return jsonify({"ok": False}), (403 if _is_guest(claims) else 200)
        from bson import ObjectId
        from bson.errors import InvalidId

        try:
            oid = ObjectId(photo_id)
        except (InvalidId, TypeError):
            return jsonify({"ok": False}), 200
        with active_user_profile_context(build_user_profile(claims)):
            uid = current_user_id()
            if not uid:
                return jsonify({"ok": False}), 403
            doc = mongo_db["sandy_photos"].find_one({"_id": oid, "chat_id": uid})
            if not doc:
                return jsonify({"ok": False}), 404
            if doc.get("grid_id") is not None:
                _delete_bytes(mongo_db, doc["grid_id"])
            res = mongo_db["sandy_photos"].delete_one({"_id": oid, "chat_id": uid})
        return jsonify({"ok": res.deleted_count > 0}), 200


def _start_ai_tagging(photo_id, image_bytes, album) -> None:
    """Caption + tag the photo off the request path; a chosen album becomes a tag."""
    from app.features import photo_album
    from app.integrations.openai_client import chat_fn

    def _bg():
        try:
            caption, tags = photo_album.generate_tags(image_bytes, chat_fn())
            if album and album not in tags:
                tags = [album] + tags
            if caption or tags:
                photo_album.set_ai_metadata(photo_id, caption, tags)
        except Exception as e:  # noqa: BLE001
            logger.info("[photos_api] background tagging failed: %s", e)

    from app.utils.thread_pool import submit_background
    submit_background(_bg, _label="photo-tags")
