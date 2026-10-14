"""Signed firmware releases that robots pull (they sit behind NAT; nothing can push).

Images are signed offline with ECDSA P-256 (scripts/publish_firmware.py) over
``sandy-fw|<version>|<size>|<sha256>``; the board verifies before switching
partitions. Rollout: canary ids, then a stable hash bucket of the fleet. ``_id`` is
the version. Releases of the retired camera and room boards (a ``board`` field,
``_id`` ``<board>:<version>``) stay in the database and are never read.
Metadata in ``sandy_firmware``, image in 1 MB chunks in ``sandy_firmware_chunks``;
keyed by version, not tenant.
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
# The brain's OTA slot; older robots refuse bigger images themselves.
MAX_IMAGE_BYTES = 0x400000
# Brain releases predate the `board` field; a retired board's carry theirs.
_BRAIN_ONLY = {"board": {"$in": [None, "brain"]}}
_VERSION_RE = re.compile(r"^\d{1,4}(\.\d{1,4}){1,3}$")


def version_key(version: str) -> tuple:
    """Numeric, part by part: "0.10.2" > "0.9.9"."""
    return tuple(int(p) for p in str(version).split("."))


def bucket(device_id: str) -> int:
    """Stable 0..99 per device."""
    return int(hashlib.sha256((device_id or "").encode()).hexdigest()[:8], 16) % 100


def is_brain(board: Optional[str]) -> bool:
    """A request naming no board, or the brain. Anything else is a retired board asking,
    which is refused rather than handed the brain's image."""
    return (board or "brain").strip().lower() == "brain"


def publish(version: str, image: bytes, signature_hex: str, *,
            rollout: int = 0, canary: Optional[List[str]] = None,
            notes: str = "") -> Dict[str, Any]:
    """Store a signed release; refuses one not newer than every published (robots never downgrade)."""
    db = get_db()
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

    key = version
    sha = hashlib.sha256(image).hexdigest()
    chunks = db[_CHUNKS]
    chunks.delete_many({"version": key})
    for n, start in enumerate(range(0, len(image), _CHUNK)):
        chunks.insert_one({"version": key, "n": n,
                           "data": image[start:start + _CHUNK]})
    meta = {
        "_id": key,
        "version": version,
        "size": len(image),
        "sha256": sha,
        "signature": signature_hex.lower(),
        "rollout": max(0, min(100, int(rollout))),
        "canary": [str(c).strip() for c in (canary or []) if str(c).strip()],
        "notes": (notes or "")[:500],
        "published_at": datetime.now(timezone.utc),
    }
    db[_META].insert_one(meta)
    logger.info("[firmware] published %s (%d bytes, rollout %d%%)",
                version, len(image), rollout)
    _prune()
    return {"ok": True, "version": version, "size": len(image), "sha256": sha}


def set_rollout(version: str, rollout: int,
                canary: Optional[List[str]] = None) -> Dict[str, Any]:
    db = get_db()
    if db is None:
        return {"ok": False, "error": "no_store"}
    changes: Dict[str, Any] = {"rollout": max(0, min(100, int(rollout)))}
    if canary is not None:
        changes["canary"] = [str(c).strip() for c in canary if str(c).strip()]
    r = db[_META].update_one({"_id": version, **_BRAIN_ONLY}, {"$set": changes})
    if r.matched_count == 0:
        return {"ok": False, "error": "not_found"}
    _prune()
    return {"ok": True, "version": version, **changes}


def _prune() -> None:
    """Keep the newest release out to every board (rollout 100) and every newer one; delete
    the older ones and their images (about seven megabytes each, kept for ever before). A
    board behind is offered the stable one, never an older one, so nothing kept is lost."""
    db = get_db()
    releases = _releases()
    stable = next((r for r in releases if int(r.get("rollout", 0)) >= 100), None)
    if db is None or stable is None:
        return
    floor = version_key(stable["version"])
    for old in releases:
        if version_key(old["version"]) >= floor:
            continue
        db[_CHUNKS].delete_many({"version": old["version"]})
        db[_META].delete_one({"_id": old["version"]})
        logger.info("[firmware] deleted %s (older than the stable %s)",
                    old["version"], stable["version"])


def release(version: str) -> Optional[Dict[str, Any]]:
    db = get_db()
    if db is None:
        return None
    return db[_META].find_one({"_id": version, **_BRAIN_ONLY}, {"_id": 0})


def latest_release() -> Optional[Dict[str, Any]]:
    db = get_db()
    if db is None:
        return None
    # Sort numerically in Python ("0.10" < "0.9" as strings).
    docs = list(db[_META].find(_BRAIN_ONLY, {"_id": 0}).limit(500))
    return max(docs, key=lambda d: version_key(d["version"])) if docs else None


def _releases() -> List[Dict[str, Any]]:
    """The releases, newest first (sorted numerically: "0.10" > "0.9")."""
    db = get_db()
    if db is None:
        return []
    docs = list(db[_META].find(_BRAIN_ONLY, {"_id": 0}).limit(500))
    return sorted(docs, key=lambda d: version_key(d["version"]), reverse=True)


def manifest_for(device_id: str, current: str) -> Optional[Dict[str, Any]]:
    """The newest release newer than `current` that this board is in the rollout of. Not
    the newest release alone: a canary held at 0 % would hide the stable one under it."""
    device_id = (device_id or "").strip()
    try:
        have = version_key(current) if current else None
    except ValueError:
        have = None  # unreadable current version counts as older
    rel = None
    for candidate in _releases():
        if have is not None and version_key(candidate["version"]) <= have:
            return None
        if device_id in candidate.get("canary", []) or bucket(device_id) < candidate.get("rollout", 0):
            rel = candidate
            break
    if rel is None:
        return None
    return {
        "version": rel["version"],
        "size": rel["size"],
        "sha256": rel["sha256"],
        "signature": rel["signature"],
    }


def image_chunks(version: str) -> Optional[Iterator[bytes]]:
    """The image chunk by chunk, or None if there is no such release."""
    db = get_db()
    if db is None:
        return None
    key = version
    if not db[_META].find_one({"_id": key, **_BRAIN_ONLY}, {"_id": 1}):
        return None

    def _gen() -> Iterator[bytes]:
        # بلا سقف: a partial image is a failed update, not a smaller one.
        for doc in db[_CHUNKS].find({"version": key}).sort("n", 1):
            yield bytes(doc["data"])
    return _gen()
