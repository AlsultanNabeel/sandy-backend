"""Chat attachments: photos and documents the user sends, and images Sandy draws.

One doc per attachment in `sandy_attachments`, scoped to its owner:
{_id, user_id, kind: image|file, name, mime, size, data (bytes), text, source, created_at}.
A document's text is pulled out once, at upload, and that text is what Sandy reads;
an image goes to the model as itself. Bytes stay inline: the limits keep each doc far
from Mongo's 16 MB cap.
"""

from __future__ import annotations

import io
import re
import uuid
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import Binary

from app.db import get_db
from app.utils.tenant_db import scoped

COLL = "sandy_attachments"

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_FILE_BYTES = 5 * 1024 * 1024
# What Sandy reads of one document; the rest is cut with a note.
MAX_TEXT_CHARS = 20_000
MAX_PER_MESSAGE = 4

IMAGE_TYPES = {"image/jpeg", "image/png", "image/heic", "image/webp", "image/gif"}
TEXT_TYPES = {"text/plain", "text/markdown", "text/csv", "application/json", "text/html"}
PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

TOO_BIG_IMAGE = "الصورة أكبر من ثمانية ميغا. صغّرها أو اختار وحدة تانية."
TOO_BIG_FILE = "الملف أكبر من خمسة ميغا. ابعت ملف أصغر أو جزء منه."
UNSUPPORTED = "ما بقدر أقرأ هالنوع. ابعت صورة، أو PDF، أو Word، أو ملف نص."
UNREADABLE = "ما قدرت أطلع نص من هالملف. ممكن يكون صور بس أو محمي."


class AttachmentError(ValueError):
    """Refused, with the line to show the user; `code` for the API."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _coll():
    db = get_db()
    return scoped(db, COLL) if db is not None else None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def kind_of(mime: str) -> str:
    if mime in IMAGE_TYPES:
        return "image"
    if mime in TEXT_TYPES or mime in (PDF, DOCX):
        return "file"
    raise AttachmentError("unsupported_type", UNSUPPORTED, 415)


def _docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
    xml = re.sub(r"</w:p>", "\n", xml)
    return re.sub(r"<[^>]+>", "", xml)


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    return "\n".join((page.extract_text() or "") for page in PdfReader(io.BytesIO(data)).pages)


def extract_text(data: bytes, mime: str) -> str:
    """The document's words, cut at MAX_TEXT_CHARS with a note; raises when there are none."""
    from pypdf.errors import PyPdfError

    try:
        if mime == PDF:
            text = _pdf_text(data)
        elif mime == DOCX:
            text = _docx_text(data)
        else:
            text = data.decode("utf-8", "ignore")
            if mime == "text/html":
                text = re.sub(r"<[^>]+>", " ", text)
    except (ValueError, KeyError, zipfile.BadZipFile, OSError, PyPdfError) as exc:
        raise AttachmentError("unreadable", UNREADABLE, 422) from exc
    text = re.sub(r"[ \t]+", " ", text).strip()
    if not text:
        raise AttachmentError("unreadable", UNREADABLE, 422)
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + "\n[… الملف أطول من هيك، هاد أول جزء منه بس]"
    return text


def save(data: bytes, name: str, mime: str, *, source: str = "upload") -> Dict[str, Any]:
    """Store one attachment for the current user; raises AttachmentError when refused."""
    mime = (mime or "").lower().split(";")[0].strip()
    kind = kind_of(mime)
    limit, too_big = (MAX_IMAGE_BYTES, TOO_BIG_IMAGE) if kind == "image" else (MAX_FILE_BYTES, TOO_BIG_FILE)
    if len(data) > limit:
        raise AttachmentError("too_big", too_big, 413)
    coll = _coll()
    if coll is None:
        raise AttachmentError("not_saved", "ما قدرت أحفظ المرفق هلّق، جرّب كمان شوي.", 503)
    doc = {
        "_id": uuid.uuid4().hex,
        "kind": kind,
        "name": (name or ("image" if kind == "image" else "file")).strip()[:120],
        "mime": mime,
        "size": len(data),
        "data": Binary(data),
        "text": extract_text(data, mime) if kind == "file" else "",
        "source": source,
        "created_at": _now(),
    }
    coll.insert_one(doc)
    return public(doc)


def public(doc: Dict[str, Any]) -> Dict[str, Any]:
    """What the app sees: no bytes, no text."""
    return {"id": doc["_id"], "kind": doc["kind"], "name": doc.get("name", ""),
            "mime": doc.get("mime", ""), "size": doc.get("size", 0)}


def get(attachment_id: str) -> Optional[Dict[str, Any]]:
    coll = _coll()
    if coll is None or not attachment_id:
        return None
    return coll.find_one({"_id": attachment_id})


def for_message(ids: List[str]) -> List[Dict[str, Any]]:
    """The current user's attachments among `ids` (others' are skipped), in order."""
    out = []
    for attachment_id in [str(i) for i in (ids or [])][:MAX_PER_MESSAGE]:
        doc = get(attachment_id)
        if doc is not None:
            out.append(doc)
    return out
