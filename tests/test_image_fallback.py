"""FLUX that timed out is still drawing (and billing): falling back to DALL-E then pays
twice and takes two minutes, past the worker's limit. A real failure still falls back."""
import pytest
import requests


@pytest.fixture()
def providers(monkeypatch):
    from app.integrations import azure_flux, azure_image

    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "k")
    calls = {"dalle": 0}

    def _dalle(*a, **k):
        calls["dalle"] += 1
        return b"dalle"
    monkeypatch.setattr(azure_image, "generate_image_with_azure_dalle", _dalle)
    monkeypatch.setattr(azure_image, "edit_image_with_azure_gptimg", _dalle)

    def flux_does(fn):
        monkeypatch.setattr(azure_flux.requests, "post", fn)
    return calls, flux_does


def _timeout(*a, **k):
    raise requests.Timeout("read timed out")


def _refused(*a, **k):
    raise requests.ConnectionError("refused")


def test_a_flux_timeout_does_not_fall_back(providers):
    from app.features import vision

    calls, flux_does = providers
    flux_does(_timeout)
    assert vision.generate_image_with_azure("قطة") is None
    assert vision.edit_image_with_azure(b"img", "خلّيها ليل") is None
    assert calls["dalle"] == 0


def test_a_flux_failure_still_falls_back(providers):
    from app.features import vision

    calls, flux_does = providers
    flux_does(_refused)
    assert vision.generate_image_with_azure("قطة") == b"dalle"
    assert calls["dalle"] == 1
