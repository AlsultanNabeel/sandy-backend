"""Firmware releases — what a robot downloads when it updates itself.

**Why the robot pulls instead of being pushed.** A sold robot sits behind
somebody else's router; nothing can reach it from outside. So each board asks
this server what the current release is, on boot and every few hours, and
fetches it if it is newer. The owner publishes once; every robot converges.

**Why a release is signed.** The image is signed with the owner's private key
(ECDSA P-256), which never leaves his machine (`scripts/publish_firmware.py`).
The board carries the public key and refuses anything the signature does not
cover: a compromised server, a wrong upload or a tampered download can at worst
make a robot skip an update, never install a foreign image. The signature covers
``sandy-fw|<version>|<size>|<sha256>``; the board checks the size and the
SHA-256 of what it actually wrote before it switches partitions.

**Why a rollout percentage.** A release reaches the canary boards (listed by id,
the owner's own first) and then a stable fraction of the fleet: ``bucket`` is a
hash of the device id, so the same robots are in the first 10 % every time and a
bad image does not reach everyone at once. The bootloader's rollback still
catches an image that cannot get back on the network.

Storage: metadata in ``sandy_firmware``; the image in 1 MB chunks in
``sandy_firmware_chunks`` (no GridFS — it needs a real driver database, and the
image is small). Keyed by version, not tenant: this is device infrastructure.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

from app.db import get_db

logger = logging.getLogger(__name__)

_META = "sandy_firmware"
_CHUNKS = "sandy_firmware_chunks"
_CHUNK = 1024 * 1024
MAX_IMAGE_BYTES = 0x1E0000          # the ota_0/ota_1 partition size
_VERSION_RE = re.compile(r"^\d{1,4}(\.\d{1,4}){1,3}$")


def version_key(version: str) -> tuple:
    """"0.10.2" > "0.9.9" — numeric, part by part."""
    return tuple(int(p) for p in str(version).split("."))


def signed_message(version: str, size: int, sha256_hex: str) -> bytes:
    """Exactly what the signature covers; the firmware builds the same string."""
    return f"sandy-fw|{version}|{int(size)}|{sha256_hex.lower()}".encode()


def bucket(device_id: str) -> int:
    """A stable 0..99 per device, for staged rollout."""
    return int(hashlib.sha256((device_id or "").encode()).hexdigest()[:8], 16) % 100


def _db():
    return get_db()


def publish(version: str, image: bytes, signature_hex: str, *,
            rollout: int = 0, canary: Optional[List[str]] = None,
            notes: str = "") -> Dict[str, Any]:
    """Store a signed release. Refuses a version that is not newer than every
    published one — a robot never installs a downgrade, so publishing one would
    only look like it worked."""
    db = _db()
    if db is None:
        return {"ok": False, "error": "no_store"}
    version = (version or "").strip()
    if not _VERSION_RE.match(version):
        return {"ok": False, "error": "bad_version"}
    if not image or len(image) > MAX_IMAGE_BYTES:
        return {"ok": False, "error": "bad_size"}
    try:
        bytes.fromhex(signature_hex)
    except ValueError:
        return {"ok": False, "error": "bad_signature"}
    latest = latest_release()
    if latest and version_key(version) <= version_key(latest["version"]):
        return {"ok": False, "error": "not_newer", "latest": latest["version"]}

    sha = hashlib.sha256(image).hexdigest()
    chunks = db[_CHUNKS]
    chunks.delete_many({"version": version})
    for n, start in enumerate(range(0, len(image), _CHUNK)):
        chunks.insert_one({"version": version, "n": n,
                           "data": image[start:start + _CHUNK]})
    db[_META].insert_one({
        "_id": version,
        "version": version,
        "size": len(image),
        "sha256": sha,
        "signature": signature_hex.lower(),
        "rollout": max(0, min(100, int(rollout))),
        "canary": [str(c).strip() for c in (canary or []) if str(c).strip()],
        "notes": (notes or "")[:500],
        "published_at": datetime.now(timezone.utc),
    })
    logger.info("[firmware] published %s (%d bytes, rollout %d%%)",
                version, len(image), rollout)
    return {"ok": True, "version": version, "size": len(image), "sha256": sha}


def set_rollout(version: str, rollout: int,
                canary: Optional[List[str]] = None) -> Dict[str, Any]:
    db = _db()
    if db is None:
        return {"ok": False, "error": "no_store"}
    changes: Dict[str, Any] = {"rollout": max(0, min(100, int(rollout)))}
    if canary is not None:
        changes["canary"] = [str(c).strip() for c in canary if str(c).strip()]
    r = db[_META].update_one({"_id": version}, {"$set": changes})
    if r.matched_count == 0:
        return {"ok": False, "error": "not_found"}
    return {"ok": True, "version": version, **changes}


def latest_release() -> Optional[Dict[str, Any]]:
    db = _db()
    if db is None:
        return None
    # Few releases ever exist; sorting numerically in Python is the honest way
    # ("0.10" sorts before "0.9" as a string).
    docs = list(db[_META].find({}, {"_id": 0}).limit(500))
    return max(docs, key=lambda d: version_key(d["version"])) if docs else None


def manifest_for(device_id: str, current: str) -> Optional[Dict[str, Any]]:
    """The release this device should run, or None when it is up to date."""
    device_id = (device_id or "").strip()
    rel = latest_release()
    if not rel:
        return None
    try:
        if current and version_key(rel["version"]) <= version_key(current):
            return None
    except ValueError:
        pass  # an unreadable current version is treated as "older"
    eligible = device_id in rel.get("canary", []) or bucket(device_id) < rel.get("rollout", 0)
    if not eligible:
        return None
    return {
        "version": rel["version"],
        "size": rel["size"],
        "sha256": rel["sha256"],
        "signature": rel["signature"],
    }


def image_chunks(version: str) -> Optional[Iterator[bytes]]:
    """The image, chunk by chunk, or None if there is no such release."""
    db = _db()
    if db is None or not db[_META].find_one({"_id": version}, {"_id": 1}):
        return None

    def _gen() -> Iterator[bytes]:
        # بلا سقف: a partial image is a failed update, not a smaller one.
        for doc in db[_CHUNKS].find({"version": version}).sort("n", 1):
            yield bytes(doc["data"])
    return _gen()
