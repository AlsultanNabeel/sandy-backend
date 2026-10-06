"""Chat attachments: upload limits and text, owner-only bytes, the model sees them,
generated images become attachments, and the history keeps them."""
from __future__ import annotations

import base64
import io
import json
import uuid
import zipfile

import pytest
from brain_fakes import A, ScriptedModel, brain_db, text_reply  # noqa: F401

from app.brain import loop
from app.features import attachments
from app.utils.user_profiles import active_user_profile_context


@pytest.fixture()
def c(monkeypatch, brain_db):  # noqa: F811
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    from app.api.server import create_app
    from app.features import usage_store
    monkeypatch.setattr(usage_store, "check_and_record", lambda *a, **k: None)
    return create_app(mongo_db=brain_db).test_client()


def _h(uid="userA"):
    from app.api.auth_handlers import make_token
    return {"Authorization": f"Bearer {make_token('user', user_id=uid)}"}


def _up(c, data: bytes, name: str, mime: str, uid="userA"):
    return c.post("/api/attachments", json={"data": base64.b64encode(data).decode(),
                                            "name": name, "mime": mime}, headers=_h(uid))


def _docx(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f"<w:document><w:p><w:t>{text}</w:t></w:p></w:document>")
    return buf.getvalue()


def test_upload_reads_a_documents_text_and_keeps_the_bytes_for_the_owner(c):
    r = _up(c, _docx("فاتورة الكهربا ٣٠٠"), "bill.docx", attachments.DOCX)
    item = r.get_json()["item"]
    assert r.status_code == 200 and item["kind"] == "file" and "data" not in item
    with active_user_profile_context(A):
        assert "فاتورة الكهربا" in attachments.get(item["id"])["text"]
    img = _up(c, b"\x89PNG fake", "p.png", "image/png").get_json()["item"]
    assert c.get(f"/api/attachments/{img['id']}/file", headers=_h()).data == b"\x89PNG fake"
    assert c.get(f"/api/attachments/{img['id']}/file", headers=_h("userB")).status_code == 404


def test_limits_and_unreadable_files_get_a_clear_line(c):
    big = _up(c, b"x" * (attachments.MAX_FILE_BYTES + 1), "big.txt", "text/plain")
    assert big.status_code == 413 and "خمسة ميغا" in big.get_json()["message"]
    odd = _up(c, b"MZ", "app.exe", "application/x-msdownload")
    assert odd.status_code == 415 and odd.get_json()["message"]
    empty = _up(c, b"   ", "blank.txt", "text/plain")
    assert empty.status_code == 422


def test_the_model_sees_the_photo_and_reads_the_document(brain_db):  # noqa: F811
    with active_user_profile_context(A):
        photo = attachments.save(b"\xff\xd8jpeg", "cat.jpg", "image/jpeg")
        doc = attachments.save("سطر من ملف".encode(), "notes.txt", "text/plain")
        model = ScriptedModel(text_reply("قطة حلوة"))
        state = loop.run_turn("شو هاد؟", user_id="userA", chat_id="userA", source="web",
                              attachments=attachments.for_message([photo["id"], doc["id"]]),
                              complete=model)
    assert state["final_response"] == "قطة حلوة"
    content = model.seen[0][-1]["content"]
    assert content[0]["type"] == "text" and "سطر من ملف" in content[0]["text"]
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    from app.brain.stm import load
    assert "[صورة: cat.jpg]" in load("userA", "userA")[-2]["content"]


def test_a_drawn_image_is_kept_as_an_attachment_and_the_history_keeps_it(c, monkeypatch):
    def fake_turn(message, **kw):
        return {"final_response": "تفضّل", "execution_result": {"image_bytes": b"\x89PNG drawn"}}
    monkeypatch.setattr(loop, "run_turn", fake_turn)
    r = c.post("/api/agent", json={"message": "ارسميلي قطة"}, headers=_h())
    image = r.get_json()["image"]
    assert image["kind"] == "image" and "image_url" not in r.get_json()
    assert c.get(f"/api/attachments/{image['id']}/file", headers=_h()).data == b"\x89PNG drawn"

    cid = uuid.uuid4().hex
    c.post(f"/api/conversations/{cid}/messages",
           json={"role": "sandy", "text": "تفضّل", "attachments": [image]}, headers=_h())
    msgs = c.get(f"/api/conversations/{cid}", headers=_h()).get_json()["messages"]
    assert msgs[-1]["attachments"] == [{"id": image["id"], "kind": "image", "name": "sandy.png"}]
    json.dumps(msgs)  # the history stays plain JSON


def test_a_small_word_file_that_unpacks_huge_is_refused():
    """Five megabytes packed can be gigabytes unpacked; the server read it whole."""
    import io
    import zipfile

    from app.features import attachments as att

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        with z.open("word/document.xml", "w") as f:
            chunk = b"\x00" * (1 << 20)
            for _ in range(att.MAX_DOCX_XML_BYTES // len(chunk) + 8):
                f.write(chunk)
    packed = buf.getvalue()
    assert len(packed) < att.MAX_FILE_BYTES
    with pytest.raises(att.AttachmentError) as err:
        att.extract_text(packed, att.DOCX)
    assert err.value.code == "too_big"


def test_a_long_pdf_stops_being_read_once_there_is_enough_text(monkeypatch):
    """Every page used to be read before the text was cut at 20 000 characters."""
    import pypdf

    from app.features import attachments as att

    read = {"n": 0}

    class _Page:
        def extract_text(self):
            read["n"] += 1
            return "كلمة " * 400          # 2000 characters a page

    class _Reader:
        def __init__(self, _stream):
            self.pages = [_Page() for _ in range(3000)]

    monkeypatch.setattr(pypdf, "PdfReader", _Reader)
    text = att.extract_text(b"%PDF-1.4", att.PDF)
    assert read["n"] <= att.MAX_TEXT_CHARS // 2000 + 1, f"{read['n']} pages read"
    assert len(text) <= att.MAX_TEXT_CHARS + 100


def test_a_pdf_of_blank_pages_is_read_only_up_to_the_page_cap(monkeypatch):
    import pypdf

    from app.features import attachments as att

    read = {"n": 0}

    class _Page:
        def extract_text(self):
            read["n"] += 1
            return ""

    class _Reader:
        def __init__(self, _stream):
            self.pages = [_Page() for _ in range(5000)]

    monkeypatch.setattr(pypdf, "PdfReader", _Reader)
    with pytest.raises(att.AttachmentError):
        att.extract_text(b"%PDF-1.4", att.PDF)
    assert read["n"] == att.MAX_PDF_PAGES


def test_an_attachment_is_kept_thirty_days(brain_db):  # noqa: F811
    from datetime import timedelta

    with active_user_profile_context(A):
        item = attachments.save(b"\x89PNG", "p.png", "image/png")
        doc = attachments.get(item["id"])
    assert doc["expire_at"] - doc["created_at"] == timedelta(days=attachments.KEEP_DAYS)


def test_attachments_from_before_the_limit_get_thirty_days_from_today(brain_db):  # noqa: F811
    """Turning the limit on must not delete every older attachment at once."""
    from datetime import datetime, timedelta, timezone

    long_ago = datetime.now(timezone.utc) - timedelta(days=200)
    brain_db["sandy_attachments"].insert_one({"_id": "old", "user_id": "userA",
                                              "kind": "image", "created_at": long_ago})
    from app import bootstrap
    bootstrap.ensure_indexes()
    doc = brain_db["sandy_attachments"].find_one({"_id": "old"})
    left = doc["expire_at"].replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)
    assert timedelta(days=attachments.KEEP_DAYS - 1) < left <= timedelta(days=attachments.KEEP_DAYS)
    ttl = [i for i in brain_db["sandy_attachments"].list_indexes()
           if i.get("expireAfterSeconds") == 0]
    assert ttl and list(ttl[0]["key"]) == ["expire_at"]


def test_an_upload_counts_against_the_day(c, monkeypatch):
    from app.features import usage_store

    monkeypatch.setattr(usage_store, "check_and_record", lambda *a, **k: "daily_quota_exceeded")
    r = _up(c, b"\x89PNG fake", "p.png", "image/png")
    assert r.status_code == 429


def test_an_iphone_photo_format_the_model_cannot_read_is_refused(c):
    """HEIC used to be stored and then handed to the model, which cannot read it."""
    r = _up(c, b"\x00\x00\x00\x18ftypheic", "IMG_1.heic", "image/heic")
    assert r.status_code == 415 and r.get_json()["message"]
