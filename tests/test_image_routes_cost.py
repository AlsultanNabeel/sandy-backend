"""The image routes spend money on a provider: nothing reaches it, and nothing is
charged, for a request that was going to be refused anyway."""
import base64

import mongomock
import pytest


@pytest.fixture()
def client(monkeypatch):
    from app.api.server import create_app
    from app.features import usage_store

    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    charged = []
    monkeypatch.setattr(usage_store, "check_and_record",
                        lambda *a, **k: charged.append(a) or None)
    app = create_app(mongo_db=mongomock.MongoClient().db)
    return app.test_client(), charged


def _bearer(uid="u1"):
    from app.api.auth_handlers import make_token
    return {"Authorization": f"Bearer {make_token('user', user_id=uid)}"}


_IMAGE = base64.b64encode(b"\xff\xd8 not really a jpeg").decode()


def test_an_endless_question_about_a_photo_never_reaches_the_model(client, monkeypatch):
    from app.features import vision

    c, charged = client
    called = []
    monkeypatch.setattr(vision, "analyze_image_with_azure",
                        lambda *a, **k: called.append(a) or "وصف")
    r = c.post("/api/analyze-image", json={"image": _IMAGE, "question": "ليش؟ " * 20_000},
               headers=_bearer())
    assert r.status_code == 413
    assert not called and not charged


@pytest.mark.parametrize("path, body", [
    ("/api/analyze-image", {"image": "not base64!!"}),
    ("/api/image/edit", {"prompt": "خلّيها ليل", "image": "not base64!!"}),
])
def test_an_image_that_does_not_decode_costs_nothing(client, path, body):
    c, charged = client
    r = c.post(path, json=body, headers=_bearer())
    assert r.status_code == 400
    assert not charged, "a broken upload used up a unit of the day's quota"

