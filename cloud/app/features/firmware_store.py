"""Signed firmware releases that robots pull (they sit behind NAT; nothing can push).

Images are signed offline with ECDSA P-256 (scripts/publish_firmware.py) over
``sandy-fw|<version>|<size>|<sha256>`` (non-brain boards add ``<board>|``); the
board verifies before switching partitions. Rollout: canary ids, then a stable
hash bucket of the fleet. Boards: brain (``_id`` = version, no ``board`` field,
for robots already in the field), cam and room (``<board>:<version>``).
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
# Largest slot of any board; older robots refuse bigger images themselves.
MAX_IMAGE_BYTES = 0x400000
BRAIN = "brain"
# Board → OTA slot size.
BOARD_SLOT_BYTES = {BRAIN: 0x400000, "cam": 0x1E0000, "room": 0x140000}
BOARDS = frozenset(BOARD_SLOT_BYTES)
_VERSION_RE = re.compile(r"^\d{1,4}(\.\d{1,4}){1,3}$")


def version_key(version: str) -> tuple:
    """Numeric, part by part: "0.10.2" > "0.9.9"."""
    return tuple(int(p) for p in str(version).split("."))


def bucket(device_id: str) -> int:
    """Stable 0..99 per device."""
    return int(hashlib.sha256((device_id or "").encode()).hexdigest()[:8], 16) % 100


def _key(board: str, version: str) -> str:
    return version if board == BRAIN else f"{board}:{version}"


def _board_filter(board: str) -> Dict[str, Any]:
    # Brain releases predate the field; a missing board means the brain.
    return {"board": {"$in": [None, BRAIN]}} if board == BRAIN else {"board": board}


def norm_board(board: Optional[str]) -> Optional[str]:
    b = (board or BRAIN).strip().lower()
    return b if b in BOARDS else None


def publish(version: str, image: bytes, signature_hex: str, *,
            rollout: int = 0, canary: Optional[List[str]] = None,
            notes: str = "", board: str = BRAIN) -> Dict[str, Any]:
    """Store a signed release; refuses one not newer than every published (robots never downgrade)."""
    db = get_db()
    if db is None:
        return {"ok": False, "error": "no_store"}
    board = norm_board(board)
    if board is None:
        return {"ok": False, "error": "bad_board"}
    version = (version or "").strip()
    if not _VERSION_RE.match(version):
        return {"ok": False, "error": "bad_version"}
    if not image or len(image) > BOARD_SLOT_BYTES[board]:
        return {"ok": False, "error": "bad_size"}
    try:
        bytes.fromhex(signature_hex)
    except ValueError:
        return {"ok": False, "error": "bad_signature"}
    latest = latest_release(board)
    if latest and version_key(version) <= version_key(latest["version"]):
        return {"ok": False, "error": "not_newer", "latest": latest["version"]}

    key = _key(board, version)
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
    if board != BRAIN:
        meta["board"] = board
    db[_META].insert_one(meta)
    logger.info("[firmware] published %s %s (%d bytes, rollout %d%%)",
                board, version, len(image), rollout)
    return {"ok": True, "board": board, "version": version, "size": len(image),
            "sha256": sha}


def set_rollout(version: str, rollout: int,
                canary: Optional[List[str]] = None, board: str = BRAIN) -> Dict[str, Any]:
    db = get_db()
    if db is None:
        return {"ok": False, "error": "no_store"}
    board = norm_board(board)
    if board is None:
        return {"ok": False, "error": "bad_board"}
    changes: Dict[str, Any] = {"rollout": max(0, min(100, int(rollout)))}
    if canary is not None:
        changes["canary"] = [str(c).strip() for c in canary if str(c).strip()]
    r = db[_META].update_one({"_id": _key(board, version)}, {"$set": changes})
    if r.matched_count == 0:
        return {"ok": False, "error": "not_found"}
    return {"ok": True, "board": board, "version": version, **changes}


def release(version: str, board: str = BRAIN) -> Optional[Dict[str, Any]]:
    db = get_db()
    if db is None or norm_board(board) is None:
        return None
    return db[_META].find_one({"_id": _key(norm_board(board), version)}, {"_id": 0})


def latest_release(board: str = BRAIN) -> Optional[Dict[str, Any]]:
    db = get_db()
    board = norm_board(board)
    if db is None or board is None:
        return None
    # Sort numerically in Python ("0.10" < "0.9" as strings).
    docs = list(db[_META].find(_board_filter(board), {"_id": 0}).limit(500))
    return max(docs, key=lambda d: version_key(d["version"])) if docs else None


def _releases(board: str) -> List[Dict[str, Any]]:
    """This board's releases, newest first (sorted numerically: "0.10" > "0.9")."""
    db = get_db()
    if db is None:
        return []
    docs = list(db[_META].find(_board_filter(board), {"_id": 0}).limit(500))
    return sorted(docs, key=lambda d: version_key(d["version"]), reverse=True)


def manifest_for(device_id: str, current: str,
                 board: str = BRAIN) -> Optional[Dict[str, Any]]:
    """The newest release newer than `current` that this board is in the rollout of. Not
    the newest release alone: a canary held at 0 % would hide the stable one under it."""
    device_id = (device_id or "").strip()
    board = norm_board(board) or BRAIN
    try:
        have = version_key(current) if current else None
    except ValueError:
        have = None  # unreadable current version counts as older
    rel = None
    for candidate in _releases(board):
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


def image_chunks(version: str, board: str = BRAIN) -> Optional[Iterator[bytes]]:
    """The image chunk by chunk, or None if there is no such release."""
    db = get_db()
    board = norm_board(board)
    if db is None or board is None:
        return None
    key = _key(board, version)
    if not db[_META].find_one({"_id": key}, {"_id": 1}):
        return None

    def _gen() -> Iterator[bytes]:
        # بلا سقف: a partial image is a failed update, not a smaller one.
        for doc in db[_CHUNKS].find({"version": key}).sort("n", 1):
            yield bytes(doc["data"])
    return _gen()
