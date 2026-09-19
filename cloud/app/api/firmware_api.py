"""Firmware update endpoints (see ``features/firmware_store``).

  GET  /api/firmware/manifest?device_id=&v=   what this robot should run (204 = nothing)
  GET  /api/firmware/image/<version>           the signed image, streamed
  POST /api/firmware/publish                   upload a release  (Bearer SANDY_FIRMWARE_TOKEN)
  POST /api/firmware/rollout                   widen/narrow it   (Bearer SANDY_FIRMWARE_TOKEN)

The two GETs are public on purpose: a robot has no account, and nothing here is
secret — the image is useless without being signed by the owner's key, and the
board verifies that signature before it installs anything.
"""

from __future__ import annotations

import hmac
import logging

from flask import Response, jsonify, request

from app.features import firmware_store

logger = logging.getLogger(__name__)


def _publisher_ok() -> bool:
    from app.config import SANDY_FIRMWARE_TOKEN
    if not SANDY_FIRMWARE_TOKEN:
        return False
    got = (request.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
    return bool(got) and hmac.compare_digest(got, SANDY_FIRMWARE_TOKEN)


def register_firmware_api(app):
    @app.route("/api/firmware/manifest", methods=["GET"])
    def firmware_manifest():
        device_id = (request.args.get("device_id") or "").strip()[:64]
        current = (request.args.get("v") or "").strip()[:32]
        m = firmware_store.manifest_for(device_id, current)
        if not m:
            return "", 204
        m["url"] = f"/api/firmware/image/{m['version']}"
        return jsonify(m), 200

    @app.route("/api/firmware/image/<version>", methods=["GET"])
    def firmware_image(version):
        rel = firmware_store.latest_release()
        chunks = firmware_store.image_chunks(version)
        if chunks is None:
            return jsonify({"error": "not_found"}), 404
        size = rel["size"] if rel and rel["version"] == version else None
        headers = {"Content-Length": str(size)} if size else {}
        return Response(chunks, mimetype="application/octet-stream", headers=headers)

    @app.route("/api/firmware/publish", methods=["POST"])
    def firmware_publish():
        if not _publisher_ok():
            return jsonify({"error": "unauthorized"}), 401
        f = request.files.get("image")
        if f is None:
            return jsonify({"error": "image_required"}), 400
        image = f.read(firmware_store.MAX_IMAGE_BYTES + 1)
        form = request.form
        try:
            rollout = int(form.get("rollout") or 0)
        except ValueError:
            return jsonify({"error": "bad_rollout"}), 400
        canary = [c for c in (form.get("canary") or "").split(",") if c.strip()]
        r = firmware_store.publish(
            form.get("version") or "", image, form.get("signature") or "",
            rollout=rollout, canary=canary, notes=form.get("notes") or "")
        return jsonify(r), (200 if r.get("ok") else 400)

    @app.route("/api/firmware/rollout", methods=["POST"])
    def firmware_rollout():
        if not _publisher_ok():
            return jsonify({"error": "unauthorized"}), 401
        body = request.get_json(silent=True) or {}
        try:
            rollout = int(body.get("rollout"))
        except (TypeError, ValueError):
            return jsonify({"error": "bad_rollout"}), 400
        canary = body.get("canary")
        r = firmware_store.set_rollout(str(body.get("version") or ""), rollout,
                                       canary if isinstance(canary, list) else None)
        return jsonify(r), (200 if r.get("ok") else 400)
