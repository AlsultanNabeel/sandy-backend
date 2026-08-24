"""«ما لقيت» and «ما قدرت أدوّر» are different facts, and only one is true.

From the owner's log:

    [Places] failed: 403 Client Error: Forbidden
    tool research_places ok: ما لقيت أماكن تطابق 'محل خضار'.

The key was rejected. No search happened. And she told him, out loud and with
confidence, that there are no greengrocers — so he went looking somewhere else.
The log knew; the person did not.

This is the shape of nearly everything that went wrong this week: an error is
caught, flattened into an empty value, and the empty value is rendered as an
answer. A refusal that returns `[]` is indistinguishable from a world with
nothing in it, and the system had no way to tell the two apart because the two
had the same type.

So the rule these tests hold: **a failure must never arrive as an empty
success.** It costs one exception class per integration.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-for-failures")

_ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


def test_a_missing_key_is_raised_rather_than_returned_as_no_results():
    from app.features.google_places import PlacesUnavailable, search_places

    with pytest.raises(PlacesUnavailable):
        search_places("محل خضار", api_key="")


def test_an_empty_query_is_still_just_an_empty_result():
    """Nothing was asked, so nothing found is honest. The distinction has to cut
    at "could the search run", not at "is the list empty"."""
    from app.features.google_places import search_places

    assert search_places("", api_key="k") == []


def test_a_refusal_from_google_becomes_unavailable_not_empty():
    """The 403 in the owner's log. It must not return a list at all."""
    import requests

    from app.features import google_places

    class _Resp:
        status_code = 403

        def raise_for_status(self):
            raise requests.HTTPError("403 Client Error: Forbidden", response=self)

    def _post(*a, **k):
        return _Resp()

    original = google_places.requests.post
    google_places.requests.post = _post
    try:
        with pytest.raises(google_places.PlacesUnavailable) as caught:
            google_places.search_places("محل خضار", api_key="k")
        assert "403" in str(caught.value)
    finally:
        google_places.requests.post = original


def test_every_caller_says_it_could_not_search():
    """Three call sites, three chances to turn it back into "nothing found"."""
    research = _read("cloud/app/features/research.py")
    assert "PlacesUnavailable" in research
    assert "البحث نفسه ما اشتغل" in research

    dispatch = _read("cloud/app/agent/executor/dispatch.py")
    assert "PlacesUnavailable" in dispatch
    assert "البحث نفسه ما" in dispatch

    api = _read("cloud/app/api/research_api.py")
    assert "PlacesUnavailable" in api
    assert "503" in api, (
        "an empty 200 tells the app a search ran and found nothing")


def test_the_two_sentences_are_not_the_same_sentence():
    """If they read alike, the distinction exists in the types and not for the
    person listening — which is the whole point of making it."""
    research = _read("cloud/app/features/research.py")
    i = research.index("if research_type == \"places\"")
    section = research[i:i + 2000]

    could_not = "خدمة الأماكن مش شغّالة عندي حاليًا"
    found_none = "ما لقيت أماكن تطابق"
    assert could_not in section and found_none in section
    assert could_not != found_none
