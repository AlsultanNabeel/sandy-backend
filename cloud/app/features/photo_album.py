"""ألبوم الصور: البايتات في GridFS (sandy_photo_files) والميتاداتا في sandy_photos.

وصف ووسوم ذكية عبر Vision؛ الاسترجاع بالاسم أو الوسم أو الوصف.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from app.db import configure, get_db

logger = logging.getLogger(__name__)

_META = "sandy_photos"
_FILES_COLLECTION = "sandy_photo_files"

_gridfs = None


def init_photo_album(mongo_db) -> None:
    global _gridfs
    configure(mongo_db)
    if mongo_db is None:
        return
    try:
        from gridfs import GridFS
        _gridfs = GridFS(mongo_db, collection=_FILES_COLLECTION)
        mongo_db[_META].create_index([("chat_id", 1), ("created_at", -1)], background=True)
        mongo_db[_META].create_index([("chat_id", 1), ("file_unique_id", 1)], background=True)
        logger.info("[photo_album] ready")
    except Exception as e:  # noqa: BLE001
        logger.warning("[photo_album] init failed: %s", e)
        _gridfs = None


def is_available() -> bool:
    return get_db() is not None and _gridfs is not None


def save_photo(
    chat_id: Any,
    image_bytes: bytes,
    *,
    file_unique_id: Optional[str] = None,
    name: Optional[str] = None,
    user_caption: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """يخزّن صورة؛ بيرجّع الموجودة لو نفس file_unique_id، أو None لو فشل."""
    if not is_available() or not image_bytes:
        return None
    cid = str(chat_id)

    if file_unique_id:
        existing = get_db()[_META].find_one(
            {"chat_id": cid, "file_unique_id": file_unique_id}
        )
        if existing:
            return existing

    try:
        grid_id = _gridfs.put(image_bytes, filename=f"{cid}_{file_unique_id or 'photo'}")
    except Exception as e:  # noqa: BLE001
        logger.warning("[photo_album] gridfs put failed: %s", e)
        return None

    caption = (user_caption or "").strip()
    doc = {
        "chat_id": cid,
        "name": (name or "").strip() or _default_name(caption),
        "grid_id": grid_id,
        "file_unique_id": file_unique_id,
        "user_caption": caption,
        "ai_caption": "",
        "tags": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    res = get_db()[_META].insert_one(doc)
    doc["_id"] = res.inserted_id
    return doc


def _default_name(caption: str) -> str:
    if caption:
        return caption[:40]
    return "صورة " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")


def set_ai_metadata(photo_id: Any, caption: str, tags: List[str]) -> None:
    """يحدّث الوصف + الوسوم الذكية (ممكن من الخلفية)."""
    if not is_available():
        return
    update: Dict[str, Any] = {}
    if caption:
        update["ai_caption"] = caption.strip()
    if tags:
        update["tags"] = [t.strip() for t in tags if t and t.strip()][:12]
    if not update:
        return
    try:
        get_db()[_META].update_one({"_id": photo_id}, {"$set": update})
    except Exception as e:  # noqa: BLE001
        logger.debug("[photo_album] set_ai_metadata failed: %s", e)


def generate_tags(image_bytes: bytes, create_chat_completion_fn) -> Tuple[str, List[str]]:
    """Vision → (وصف قصير بالعربي، قائمة وسوم). يرجّع ("", []) لو فشل."""
    if not image_bytes or create_chat_completion_fn is None:
        return "", []
    import base64

    try:
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        data_url = f"data:image/jpeg;base64,{b64}"
        prompt = (
            "حلّلي الصورة وأرجعي JSON فقط بهذا الشكل بدون أي نص إضافي:\n"
            '{"caption": "وصف قصير بالعربية بجملة واحدة", '
            '"tags": ["وسم1", "وسم2", "..."]}\n'
            "الوسوم كلمات مفتاحية عربية مفردة (أشخاص، مكان، مناسبة، ألوان، أشياء بارزة) — من 3 لـ 8 وسوم."
        )
        response = create_chat_completion_fn(
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
            temperature=0.4,
            max_tokens=300,
            prefer_azure=True,
        )
        raw = (response.choices[0].message.content or "").strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        data = json.loads(raw)
        caption = str(data.get("caption", "")).strip()
        tags = [str(t).strip() for t in (data.get("tags") or []) if str(t).strip()]
        return caption, tags
    except Exception as e:  # noqa: BLE001
        logger.info("[photo_album] generate_tags failed (no tags saved): %s", e)
        return "", []


def _text_filter(query: str) -> Dict[str, Any]:
    """Every word of the query in the name, a caption or a tag, matched in the database
    (so the whole album is searched, not a window of recent photos)."""
    import re

    fields = ("name", "user_caption", "ai_caption", "tags")
    return {"$and": [{"$or": [{f: {"$regex": re.escape(tok), "$options": "i"}} for f in fields]}
                     for tok in query.lower().split()]}


def find_photos(
    chat_id: Any,
    query: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 20,
    before: Optional[Tuple[datetime, str]] = None,
) -> List[Dict[str, Any]]:
    """يرجّع ميتاداتا الصور المطابقة (الأحدث أولاً). بدون query/tag → كل الصور.

    A page: ``before`` is the last photo of the page before, as ``(created_at, id)``."""
    if not is_available():
        return []
    clauses: List[Dict[str, Any]] = [{"chat_id": str(chat_id)}]
    if tag:
        clauses.append({"tags": tag.strip()})
    if query and query.strip():
        clauses.append(_text_filter(query))
    if before is not None:
        at, last_id = before
        clauses.append({"$or": [{"created_at": {"$lt": at}},
                                {"created_at": at, "_id": {"$lt": last_id}}]})
    try:
        return list(get_db()[_META].find({"$and": clauses})
                    .sort([("created_at", -1), ("_id", -1)]).limit(max(1, limit)))
    except Exception as e:  # noqa: BLE001
        logger.warning("[photo_album] find failed: %s", e)
        return []


def tag_counts(chat_id: Any) -> Dict[str, int]:
    """Per-tag counts over all the user's photos, computed in the database."""
    if not is_available():
        return {}
    try:
        rows = get_db()[_META].aggregate([
            {"$match": {"chat_id": str(chat_id)}},
            {"$unwind": "$tags"},
            {"$group": {"_id": "$tags", "n": {"$sum": 1}}},
        ])
        counts: Dict[str, int] = {}
        for r in rows:
            tag = str(r.get("_id") or "").strip()
            if tag:
                counts[tag] = counts.get(tag, 0) + int(r.get("n") or 0)
        return counts
    except Exception as e:  # noqa: BLE001
        logger.warning("[photo_album] tag count failed: %s", e)
        return {}
