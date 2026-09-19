#!/usr/bin/env python3
"""Sign a firmware build and publish it to the robots.

    python3 scripts/publish_firmware.py --key ~/Desktop/.sandy-signing/firmware-signing-key.pem \
        --canary 8421 [--rollout 0] [--notes "…"]

Reads the version from main/include/config.h (SANDY_FW_VERSION) and the image
from firmware/brain-core/build-retail/sandy-brain-s3.bin (the sale build). Signs
``sandy-fw|<version>|<size>|<sha256>`` with the private key (ECDSA P-256), checks
the signature against the public key compiled into the firmware — a release the
robots would refuse is caught here, not in the field — and uploads.

Needs SANDY_API_BASE (e.g. https://…herokuapp.com) and SANDY_FIRMWARE_TOKEN in
the environment (or in ~/Desktop/.sandy-publish.env as KEY=value lines).

Widen a release later:
    python3 scripts/publish_firmware.py --rollout-only 0.9.2 --rollout 25
"""

import argparse
import hashlib
import json
import os
import pathlib
import re
import sys
import urllib.request
import uuid

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

REPO = pathlib.Path(__file__).resolve().parents[1]
FW = REPO / "firmware" / "brain-core"
# The sale build (idf.py -B build-retail -DSANDY_RETAIL=1 build): LAN upload
# server off. Only this image is ever published — a dev image would hand every
# sold robot an unauthenticated flash port.
IMAGE = FW / "build-retail" / "sandy-brain-s3.bin"
CONFIG_H = FW / "main" / "include" / "config.h"
PUBLIC = FW / "main" / "fw_pubkey.pem"
ENV_FILE = pathlib.Path("~/Desktop/.sandy-publish.env").expanduser()


def _env(name: str) -> str:
    if os.environ.get(name):
        return os.environ[name].strip()
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip() == name:
                return v.strip()
    sys.exit(f"missing {name} (environment or {ENV_FILE})")


def _version() -> str:
    m = re.search(r'#define\s+SANDY_FW_VERSION\s+"([^"]+)"', CONFIG_H.read_text())
    if not m:
        sys.exit("SANDY_FW_VERSION not found in config.h")
    return m.group(1)


def _post(url: str, token: str, body: bytes, content_type: str) -> dict:
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": content_type})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, **json.loads(e.read() or b"{}")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key")
    ap.add_argument("--rollout", type=int, default=0)
    ap.add_argument("--canary", default="")
    ap.add_argument("--notes", default="")
    ap.add_argument("--rollout-only", metavar="VERSION")
    a = ap.parse_args()

    base = _env("SANDY_API_BASE").rstrip("/")
    token = _env("SANDY_FIRMWARE_TOKEN")

    if a.rollout_only:
        r = _post(f"{base}/api/firmware/rollout", token,
                  json.dumps({"version": a.rollout_only, "rollout": a.rollout}).encode(),
                  "application/json")
        print(r)
        return 0 if r.get("ok") else 1

    if not a.key:
        sys.exit("--key is required to publish")
    version = _version()
    image = IMAGE.read_bytes()
    if image[:1] != b"\xe9":
        sys.exit(f"{IMAGE} is not an ESP32 app image")
    # Belt and braces: the LAN upload server's task name only exists in a dev
    # build. If it is in here, this is not the sale build — refuse to ship it.
    if b"logsrv\x00" in image:
        sys.exit(f"{IMAGE} still has the LAN upload server (ENABLE_REMOTE) — "
                 "build with: idf.py -B build-retail -DSANDY_RETAIL=1 build")
    sha = hashlib.sha256(image).hexdigest()
    message = f"sandy-fw|{version}|{len(image)}|{sha}".encode()

    private = serialization.load_pem_private_key(
        pathlib.Path(a.key).expanduser().read_bytes(), password=None)
    signature = private.sign(message, ec.ECDSA(hashes.SHA256()))

    # The same check the robot will make, against the key built into it.
    public = serialization.load_pem_public_key(PUBLIC.read_bytes())
    try:
        public.verify(signature, message, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature:
        sys.exit("this key does not match main/fw_pubkey.pem — the robots would refuse it")

    boundary = uuid.uuid4().hex
    parts = []
    for name, value in (("version", version), ("signature", signature.hex()),
                        ("rollout", str(a.rollout)), ("canary", a.canary),
                        ("notes", a.notes)):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"'
                     f"\r\n\r\n{value}\r\n".encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="image"; '
                 f'filename="fw.bin"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()
                 + image + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    r = _post(f"{base}/api/firmware/publish", token, b"".join(parts),
              f"multipart/form-data; boundary={boundary}")
    print(f"version {version}, {len(image)} bytes, sha256 {sha[:16]}…")
    print(r)
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
