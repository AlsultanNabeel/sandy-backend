"""Photos API — the user-facing photo album (the "ألبوم" tool screen).

Reads/writes the SAME store the agent's photo tools use: photo bytes live in
GridFS (``sandy_photo_files``) and metadata in ``sandy_photos`` (one flat,
per-user collection keyed by ``chat_id``, with fields ``name``, ``grid_id``,
``user_caption``, ``ai_caption``, ``tags[]``, ``created_at``). We reuse
``app.features.photo_album`` end to end — no new schema.

Telegram decoupling: the storage layer is already Telegram-free (raw bytes in
GridFS), so every route here works purely over REST. The OLD coupling lived only
in the agent tools (they pulled the "last image" out of a Telegram session and
handed bytes back for the bot to send). Here the app uploads bytes as base64 and
fetches them back from a plain GET-bytes route. ``file_unique_id`` (a Telegram
dedup key) is optional and simply left unset for app uploads.

"Albums" are not a separate collection in this schema — a photo is tagged, and a
tag is an album. ``GET /api/photos/albums`` therefore returns the distinct tags
(each with a count); filtering by ``album`` filters by that tag.

Scoped to the caller's own ``user_id`` via ``active_user_profile_context`` so
each user only ever sees their own photos; guests get nothing (fail-closed).

Endpoints:
  GET    /api/photos                 this user's photos (optional ?album= / ?q=)
  GET    /api/photos/albums          this user's tags (album name + count)
  GET    /api/photos/<photo_id>/file the photo bytes (JPEG/PNG) for display
  POST   /api/photos                 add a photo (base64 image + optional name/album)
  DELETE /api/photos/<photo_id>      forget one photo (metadata + bytes)
"""

from __future__ import annotations

import base64
import logging
import threading

from flask import Response, jsonify, request

from app.api.auth_handlers import require_auth
from app.utils.user_profiles import (
    active_user_profile_context,
    build_user_profile,
    current_user_id,
)

logger = logging.getLogger(__name__)

# The GridFS bucket photo_album stores the raw bytes in (see
# app.features.photo_album._FILES_COLLECTION). We read/delete a photo's bytes by
# its grid id directly here so the by-id routes don't have to re-run a text
# search the way the agent's query-based helpers do.
_FILES_COLLECTION = "sandy_photo_files"


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
    """Map a ``sandy_photos`` doc to the app's flat photo shape (no bytes)."""
    return {
        "id": str(doc.get("_id", "")),
        "name": (doc.get("name") or "").strip(),
        "caption": (doc.get("ai_caption") or doc.get("user_caption") or "").strip(),
        "tags": [t for t in (doc.get("tags") or []) if t],
        "created_at": doc.get("created_at") or "",
    }


def register_photos_api(app, mongo_db=None):
    from app.features import photo_album

    # The album singleton is normally primed when the agent facade imports; prime
    # it here too so the API works even if registered before that import. Safe to
    # call again (idempotent) — it just rebinds the same GridFS handle.
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
        """Distinct tags for this user, each with how many photos carry it.
        A tag is an album in this flat schema."""
        if _is_guest(claims):
            return jsonify({"items": []}), 200
        with active_user_profile_context(build_user_profile(claims)):
            uid = current_user_id()
            if not uid:
                return jsonify({"items": []}), 200
            counts: dict[str, int] = {}
            for d in photo_album.find_photos(uid, limit=500):
                for tag in d.get("tags") or []:
                    tag = (tag or "").strip()
                    if tag:
                        counts[tag] = counts.get(tag, 0) + 1
        items = [
            {"name": name, "count": counts[name]}
            for name in sorted(counts, key=lambda n: (-counts[n], n))
        ]
        return jsonify({"items": items}), 200

    @app.route("/api/photos/<photo_id>/file", methods=["GET"])
    @require_auth
    def get_photo_file(claims, photo_id):
        """Stream a single photo's bytes for display. Scoped: the lookup matches
        only photos owned by this user, so one user can't read another's file."""
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
    @require_auth
    def add_photo(claims):
        """Add a photo from the app: base64 image bytes + optional name/album.
        Smart caption/tags are generated in the background (don't block the add)."""
        if _is_guest(claims):
            return jsonify({"error": "forbidden"}), 403
        body = request.get_json(silent=True) or {}
        image_b64 = (body.get("image") or "").strip()
        if not image_b64:
            return jsonify({"error": "image_required"}), 400
        # Accept a bare base64 string or a "data:image/...;base64,XXXX" data URI.
        if "," in image_b64 and image_b64.lstrip().startswith("data:"):
            image_b64 = image_b64.split(",", 1)[1]
        try:
            image_bytes = base64.b64decode(image_b64)
        except (ValueError, TypeError):
            return jsonify({"error": "bad_image"}), 400
        if not image_bytes:
            return jsonify({"error": "bad_image"}), 400

        name = (body.get("name") or "").strip() or None
        album = (body.get("album") or "").strip()

        with active_user_profile_context(build_user_profile(claims)):
            uid = current_user_id()
            if not uid:
                return jsonify({"error": "forbidden"}), 403
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
        """Forget one photo (metadata + GridFS bytes), scoped to this user."""
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
    """Generate the smart caption + tags off the request path (Vision is slow).
    A user-chosen album is just a tag we make sure ends up on the photo."""
    from app.agent.facade.agent import create_chat_completion
    from app.features import photo_album

    def _bg():
        try:
            caption, tags = photo_album.generate_tags(image_bytes, create_chat_completion)
            if album and album not in tags:
                tags = [album] + tags
            if caption or tags:
                photo_album.set_ai_metadata(photo_id, caption, tags)
        except Exception as e:  # noqa: BLE001
            logger.info("[photos_api] background tagging failed: %s", e)

    threading.Thread(target=_bg, daemon=True).start()
