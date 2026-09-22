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

The camera and the room node (``--board cam`` / ``--board room``):

    python3 scripts/publish_firmware.py --board cam --key … --canary cam-8421

builds the sketch itself with ``arduino-cli`` (the one inside Arduino IDE works)
from a clean copy whose ``secrets.h`` is ``secrets.example.h`` — so the image
carries no pairing code, broker key or Wi-Fi password: the board keeps its own
in NVS (``sandy_identity.h``), and the image is downloadable by anyone. It still
refuses an image that contains any value from your real ``secrets.h``, or the
LAN upload / telnet code of a dev build. The signed message names the board —
``sandy-fw|<board>|<version>|<size>|<sha256>`` — so a camera never accepts a
brain image. ``--image`` skips the build and publishes a file you built.
Their device ids for ``--canary`` are ``cam-<node>`` and ``room-<node>``.
"""

import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
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

# The two Arduino boards: sketch folder, the define that carries the version,
# the board to build for, their OTA slot, and strings only a dev build has.
SMALL_BOARDS = {
    "cam": {
        "sketch": REPO / "vision-core",
        "version_re": r'#define\s+SANDY_CAM_FW_VERSION\s+"([^"]+)"',
        "version_file": "config.h",
        "fqbn": "esp32:esp32:esp32cam",
        "slot": 0x1E0000,
        "dev_markers": [b"ESP32-CAM serial mirror", b"[TELNET]"],
    },
    "room": {
        "sketch": REPO / "room-node",
        "version_re": r'#define\s+SANDY_ROOM_FW_VERSION\s+"([^"]+)"',
        "version_file": "room-node.ino",
        "fqbn": "esp32:esp32:esp32",
        "slot": 0x140000,
        "dev_markers": [b"[OTA] LAN ready"],
    },
}
_ARDUINO_CLI_CANDIDATES = [
    "arduino-cli",
    "/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli",
]


def _arduino_cli() -> str:
    for c in _ARDUINO_CLI_CANDIDATES:
        path = shutil.which(c) or (c if pathlib.Path(c).exists() else None)
        if path:
            return path
    sys.exit("arduino-cli not found — install it (brew install arduino-cli) or pass --image")


_SECRET_NAME = re.compile(r"PASS|KEY|PAIR|USER|SSID|TOKEN|HOST", re.I)


def _secret_values(sketch: pathlib.Path) -> list:
    """The identity values in the real secrets.h: pairing code, broker login and
    host, Wi-Fi, keys. Anything that belongs to one robot and not to all."""
    f = sketch / "secrets.h"
    if not f.exists():
        return []
    text = f.read_text()
    pairs = re.findall(r'#define\s+(\w+)\s+"([^"\n]*)"', text)
    pairs += re.findall(r'char\s*\*\s*(\w+)\s*=\s*"([^"\n]*)"', text)
    public_hosts = ("herokuapp.com",)   # the server's address is not a secret
    return [v.encode() for name, v in pairs
            if _SECRET_NAME.search(name) and not name.endswith("HOSTNAME") and len(v) >= 6
            and not v.startswith("YOUR_") and "XXXX" not in v
            and not v.endswith(public_hosts)]


def _build_small(board: str) -> bytes:
    """Build from a clean copy with the example secrets. Never the real ones."""
    cfg = SMALL_BOARDS[board]
    cli = _arduino_cli()
    with tempfile.TemporaryDirectory() as tmp:
        dst = pathlib.Path(tmp) / cfg["sketch"].name
        shutil.copytree(cfg["sketch"], dst,
                        ignore=shutil.ignore_patterns("secrets.h", "build"))
        shutil.copy(dst / "secrets.example.h", dst / "secrets.h")
        out = pathlib.Path(tmp) / "out"
        r = subprocess.run([cli, "compile", "--fqbn", cfg["fqbn"],
                            "--output-dir", str(out), str(dst)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(f"build failed:\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")
        return (out / f"{dst.name}.ino.bin").read_bytes()


def _publish_small(a, base: str, token: str) -> int:
    cfg = SMALL_BOARDS[a.board]
    src = (cfg["sketch"] / cfg["version_file"]).read_text()
    m = re.search(cfg["version_re"], src)
    if not m:
        sys.exit(f"version not found in {cfg['version_file']}")
    version = m.group(1)
    image = pathlib.Path(a.image).expanduser().read_bytes() if a.image else _build_small(a.board)
    if image[:1] != b"\xe9":
        sys.exit("not an ESP32 app image")
    if len(image) > cfg["slot"]:
        sys.exit(f"{len(image)} bytes does not fit the {a.board} slot ({cfg['slot']})")
    for marker in cfg["dev_markers"]:
        if marker in image:
            sys.exit(f"this is a dev build ({marker.decode()!r} is inside) — "
                     "remove SANDY_DEV and build again")
    for secret in _secret_values(cfg["sketch"]):
        if secret in image:
            sys.exit("the image contains a value from your real secrets.h — it would be "
                     "public on the server. Build with secrets.example.h (the default).")
    if b"sandyota" not in image:
        sys.exit("this image has no updater (sandy_ota_pull.h) — a board that installs "
                 "it could never update again")
    return _sign_and_upload(a, base, token, version, image,
                            f"sandy-fw|{a.board}|{version}|{len(image)}|", a.board)


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
    ap.add_argument("--board", choices=["brain", *SMALL_BOARDS], default="brain")
    ap.add_argument("--image", help="cam/room: publish this .bin instead of building")
    a = ap.parse_args()

    base = _env("SANDY_API_BASE").rstrip("/")
    token = _env("SANDY_FIRMWARE_TOKEN")

    if a.rollout_only:
        r = _post(f"{base}/api/firmware/rollout", token,
                  json.dumps({"version": a.rollout_only, "rollout": a.rollout,
                              "board": a.board}).encode(),
                  "application/json")
        print(r)
        return 0 if r.get("ok") else 1

    if not a.key:
        sys.exit("--key is required to publish")
    if a.board != "brain":
        return _publish_small(a, base, token)
    version = _version()
    image = IMAGE.read_bytes()
    if image[:1] != b"\xe9":
        sys.exit(f"{IMAGE} is not an ESP32 app image")
    # Belt and braces: the LAN upload server's task name only exists in a dev
    # build. If it is in here, this is not the sale build — refuse to ship it.
    if b"logsrv\x00" in image:
        sys.exit(f"{IMAGE} still has the LAN upload server (ENABLE_REMOTE) — "
                 "build with: idf.py -B build-retail -DSANDY_RETAIL=1 build")
    # The retail build compiles secrets.example.h (sandy_identity.c), so a
    # published image never carries one robot's pairing code or keys to all of
    # them. Belt and braces: refuse one that somehow does.
    for secret in _secret_values(FW / "main"):
        if secret in image:
            sys.exit("the image contains a value from main/secrets.h — it would be public "
                     "and every robot would take this one's identity. Rebuild the retail "
                     "build from a clean build-retail directory.")
    return _sign_and_upload(a, base, token, version, image,
                            f"sandy-fw|{version}|{len(image)}|", "brain")


def _sign_and_upload(a, base: str, token: str, version: str, image: bytes,
                     prefix: str, board: str) -> int:
    sha = hashlib.sha256(image).hexdigest()
    message = f"{prefix}{sha}".encode()

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
    for name, value in (("version", version), ("board", board),
                        ("signature", signature.hex()),
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
    print(f"{board} {version}, {len(image)} bytes, sha256 {sha[:16]}…")
    print(r)
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
