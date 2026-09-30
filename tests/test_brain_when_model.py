"""The model half of `brain.when`: a time expression the deterministic parser cannot read."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.brain import when


def _completion(iso_str, success=True):
    def fn(**kwargs):
        payload = {"success": success, "remind_at_iso": iso_str, "intent": "reminder",
                   "reason": "parsed", "original_text": "test"}
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(payload)))])
    return fn


@pytest.fixture
def model(monkeypatch):
    def use(fn):
        monkeypatch.setattr(when, "_chat_fn", lambda: fn)
    return use


def test_no_model_and_no_weekday_is_none(model):
    model(None)
    assert when._parse_with_model("بكرا الساعة 3") is None


def test_empty_is_none(model):
    model(_completion("2099-01-01T09:00:00"))
    assert when._parse_with_model("") is None


def test_a_weekday_needs_no_model(model, monkeypatch):
    fn = MagicMock(side_effect=AssertionError("no model call"))
    model(fn)
    monkeypatch.setattr(when, "resolve_day_name_to_iso", lambda t: "2099-12-31T09:00:00+03:00")
    assert "2099" in when._parse_with_model("الاثنين")
    fn.assert_not_called()


def test_a_past_weekday_falls_through_to_the_model(model, monkeypatch):
    model(_completion("2099-06-01T09:00:00+03:00"))
    monkeypatch.setattr(when, "resolve_day_name_to_iso", lambda t: "2000-01-01T09:00:00+03:00")
    assert "2099" in when._parse_with_model("الاثنين")


@pytest.mark.parametrize("iso, ok", [
    ("2099-06-15T10:00:00+03:00", True),
    ("2099-06-15T10:00:00", True),        # naive is the user's zone, not refused
    ("2000-01-01T10:00:00+03:00", False),  # in the past
])
def test_the_model_answer(model, iso, ok):
    model(_completion(iso))
    assert (when._parse_with_model("بكرا الساعة 10") is not None) is ok


def test_a_model_that_cannot_parse_or_raises_is_none(model):
    model(_completion(None, success=False))
    assert when._parse_with_model("شو رأيك") is None

    def boom(**kw):
        raise RuntimeError("network error")
    model(boom)
    assert when._parse_with_model("بكرا") is None
