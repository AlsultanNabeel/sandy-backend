"""Chat attachments (features/attachments): upload, and the bytes back for the app.

  POST /api/attachments {data (base64), name, mime} -> {item}   images 8 MB, documents 5 MB
  GET  /api/attachments/<id>/file                               the bytes, owner only (404 once
                                                                expired, after KEEP_DAYS)

A refusal is {error, message} with the line to show: too big (413), a type Sandy
cannot read (415), a document with no text in it (422).
"""

from __future__ import annotations

import base64
import binascii

from flask import Response, jsonify, request

from app.api.auth_handlers import require_tenant
from app.api.metering import meter_claims
from app.features import attachments as A

# The largest allowed upload in base64 characters, checked before decoding.
_MAX_B64_CHARS = (A.MAX_IMAGE_BYTES // 3 + 1) * 4


def register_attachments_api(app):
    @app.route("/api/attachments", methods=["POST"])
    @require_tenant
    def api_attachment_upload(claims):
        body = request.get_json(silent=True) or {}
        raw = body.get("data")
        if not isinstance(raw, str) or not raw:
            return jsonify({"error": "no_data", "message": "ما وصلني الملف."}), 400
        if len(raw) > _MAX_B64_CHARS:
            return jsonify({"error": "too_big", "message": A.TOO_BIG_IMAGE}), 413
        try:
            data = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError):
            return jsonify({"error": "no_data", "message": "ما وصلني الملف."}), 400
        # A document is read (and kept) on upload: one unit of the day, like a message.
        over = meter_claims(claims)
        if over is not None:
            return jsonify(over[0]), over[1]
        try:
            item = A.save(data, str(body.get("name") or ""), str(body.get("mime") or ""))
        except A.AttachmentError as exc:
            return jsonify({"error": exc.code, "message": exc.message}), exc.status
        return jsonify({"ok": True, "item": item}), 200

    @app.route("/api/attachments/<attachment_id>/file", methods=["GET"])
    @require_tenant
    def api_attachment_file(claims, attachment_id):
        doc = A.get(attachment_id)
        if doc is None:
            return jsonify({"error": "not_found"}), 404
        resp = Response(bytes(doc["data"]), mimetype=doc.get("mime") or "application/octet-stream")
        resp.headers["Cache-Control"] = "private, max-age=86400"
        return resp
