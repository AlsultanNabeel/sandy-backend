"""The fallback is a different provider: with no Azure configured the primary already is
OpenAI direct, and calling it again is the same failure twice, billed twice."""


def _primary_fails(monkeypatch):
    from app.brain import model

    def _down(*a, **k):
        raise RuntimeError("model down")
    monkeypatch.setattr(model, "_primary", _down)
    direct = []
    monkeypatch.setattr(model, "_openai_direct",
                        lambda *a, **k: direct.append(1) or None)
    return model, direct


def test_without_azure_the_same_provider_is_not_asked_twice(monkeypatch):
    from app.integrations import openai_client

    model, direct = _primary_fails(monkeypatch)
    monkeypatch.setattr(openai_client, "azure_is_primary", lambda: False)
    assert model.complete([{"role": "user", "content": "مرحبا"}], []) is None
    assert direct == []


def test_with_azure_primary_openai_direct_is_still_the_fallback(monkeypatch):
    from app.integrations import openai_client

    model, direct = _primary_fails(monkeypatch)
    monkeypatch.setattr(openai_client, "azure_is_primary", lambda: True)
    model.complete([{"role": "user", "content": "مرحبا"}], [])
    assert direct == [1]
