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
