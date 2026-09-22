"""Firmware update endpoints (see ``features/firmware_store``).

  GET  /api/firmware/manifest?device_id=&v=[&board=]   what this board should run (204 = nothing)
  GET  /api/firmware/image/<version>[?board=]           the signed image, streamed

``board`` is ``brain`` (the default — every robot in the field asks without it),
``cam`` or ``room``.
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
        board = firmware_store.norm_board(request.args.get("board"))
        if board is None:
            return jsonify({"error": "bad_board"}), 400
        m = firmware_store.manifest_for(device_id, current, board)
        if not m:
            return "", 204
        m["url"] = f"/api/firmware/image/{m['version']}"
        if board != firmware_store.BRAIN:
            m["url"] += f"?board={board}"
        return jsonify(m), 200

    @app.route("/api/firmware/image/<version>", methods=["GET"])
    def firmware_image(version):
        board = firmware_store.norm_board(request.args.get("board"))
        if board is None:
            return jsonify({"error": "bad_board"}), 400
        chunks = firmware_store.image_chunks(version, board)
        if chunks is None:
            return jsonify({"error": "not_found"}), 404
        # The length of *this* release, not only the latest: the small boards
        # read exactly Content-Length bytes and have no chunked decoder.
        rel = firmware_store.release(version, board)
        size = rel.get("size") if rel else None
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
            rollout=rollout, canary=canary, notes=form.get("notes") or "",
            board=form.get("board") or firmware_store.BRAIN)
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
                                       canary if isinstance(canary, list) else None,
                                       board=str(body.get("board") or firmware_store.BRAIN))
        return jsonify(r), (200 if r.get("ok") else 400)
