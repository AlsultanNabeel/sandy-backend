"""Why a page could not be read, told apart (`features/web_page`, `brain/tools_browser`): the page
is not there (and he is offered a search by name on the site itself, never one made on its own),
the site refused, she has no permission, or a technical failure. In both languages."""
from __future__ import annotations

import pytest
from brain_fakes import A, brain_db  # noqa: F401
from test_browser_page import Resp, web  # noqa: F401

from app.brain import lang, tools
from app.brain.ctx import TurnCtx
from app.features import web_page
from app.integrations import steel_client
from app.utils.user_profiles import active_user_profile_context

WIKI_MISSING = ("<html><body><main><p>" + "ويكيبيديا لا تحتوي على مقالة بهذا الاسم بالضبط. " * 10
                + "</p></main></body></html>")


@pytest.fixture
def steel(monkeypatch, brain_db):  # noqa: F811
    calls = []

    def scrape(url, *, screenshot=False):
        calls.append(url)
        return {"html": WIKI_MISSING, "title": "", "links": [], "screenshot": "", "status": 200}
    monkeypatch.setattr(steel_client.config, "STEEL_API_KEY", "k")
    monkeypatch.setattr(steel_client, "scrape", scrape)
    return calls


@pytest.mark.parametrize("status", [404, 410])
def test_a_page_that_is_not_there_is_missing_and_never_read_from_its_error_page(web, steel, status):  # noqa: F811
    web.hosts["ar.wikipedia.org"] = "93.184.216.34"
    web.pages["https://ar.wikipedia.org/wiki/ESP32"] = Resp(status=status, body=WIKI_MISSING.encode())
    with pytest.raises(web_page.PageError) as e:
        web_page.read("https://ar.wikipedia.org/wiki/ESP32", user_id="userA")
    assert e.value.code == "missing" and e.value.site == "ar.wikipedia.org" and steel == []


@pytest.mark.parametrize("status", [401, 403, 429, 451])
def test_a_site_that_refuses_and_no_browser_to_try_is_a_refusal(web, status):  # noqa: F811
    web.hosts["shy.example"] = "93.184.216.34"
    web.pages["https://shy.example/"] = Resp(status=status)
    with pytest.raises(web_page.PageError) as e:
        web_page.read("https://shy.example/", user_id="userA")
    assert e.value.code == "refused"


def test_a_site_that_refuses_steel_too_is_a_refusal(web, monkeypatch, brain_db):  # noqa: F811
    web.hosts["shy.example"] = "93.184.216.34"
    web.pages["https://shy.example/"] = Resp(status=403)
    monkeypatch.setattr(steel_client.config, "STEEL_API_KEY", "k")
    monkeypatch.setattr(steel_client, "scrape", lambda url, *, screenshot=False: {
        "html": "<p>Access denied</p>", "title": "", "links": [], "screenshot": "", "status": 403})
    with pytest.raises(web_page.PageError) as e:
        web_page.read("https://shy.example/", user_id="userA")
    assert e.value.code == "refused"


def test_steel_finding_no_page_is_missing(web, monkeypatch, brain_db):  # noqa: F811
    web.hosts["app.example"] = "93.184.216.34"
    web.pages["https://app.example/x"] = Resp(body=b"<p>thin</p>")
    monkeypatch.setattr(steel_client.config, "STEEL_API_KEY", "k")
    monkeypatch.setattr(steel_client, "scrape", lambda url, *, screenshot=False: {
        "html": WIKI_MISSING, "title": "", "links": [], "screenshot": "", "status": 404})
    with pytest.raises(web_page.PageError) as e:
        web_page.read("https://app.example/x", user_id="userA")
    assert e.value.code == "missing"


def test_steels_status_is_kept_from_its_answer(monkeypatch):
    monkeypatch.setattr(steel_client.config, "STEEL_API_KEY", "k")
    monkeypatch.setattr(steel_client, "_post", lambda path, body: {
        "content": {"html": "<p>x</p>"}, "metadata": {"statusCode": 404}})
    monkeypatch.setattr(steel_client.trace_store, "note_fee", lambda *a: None)
    assert steel_client.scrape("https://a.example/")["status"] == 404


def test_no_connection_is_a_technical_failure(web):  # noqa: F811
    with pytest.raises(web_page.PageError) as e:
        web_page.read("https://gone.example/", user_id="userA")
    assert e.value.code == "unreachable"


def _said(code, language, monkeypatch):
    monkeypatch.setenv("SANDY_FLAGS", '{"browser": ["userA"]}')

    def fail(url, *, user_id):
        raise web_page.PageError(code, "ar.wikipedia.org")
    monkeypatch.setattr(web_page, "read", fail)
    with active_user_profile_context({**A, "chat_id": "userA"}), lang.using(language):
        return tools.execute("page_read", {"url": "https://ar.wikipedia.org/wiki/ESP32"},
                             TurnCtx(user_id="userA", message="اقرا"))


@pytest.mark.parametrize("language, code, words", [
    ("ar", "missing", "الصفحة مش موجودة"), ("en", "missing", "doesn't exist"),
    ("ar", "refused", "رفضني"), ("en", "refused", "refused me"),
    ("ar", "private", "ما عندي إذن"), ("en", "private", "I don't have permission"),
    ("ar", "unreachable", "فشل تقني"), ("en", "unreachable", "technical failure")])
def test_each_reason_is_told_apart_in_his_language(brain_db, monkeypatch, language, code, words):  # noqa: F811
    result = _said(code, language, monkeypatch)
    assert result["ok"] is False and words in result["reply"]


@pytest.mark.parametrize("language, words", [("ar", "أدوّر عليها بالاسم"), ("en", "search for it by name")])
def test_a_missing_page_offers_a_search_by_name_on_the_site_and_makes_none(brain_db, monkeypatch, language, words):  # noqa: F811
    from app.features import research
    monkeypatch.setattr(research, "web_answer", lambda *a, **kw: pytest.fail("searched"))
    result = _said("missing", language, monkeypatch)
    assert words in result["reply"] and "ar.wikipedia.org" in result["reply"]


def test_the_four_reasons_say_four_different_things(monkeypatch):
    for language in ("ar", "en"):
        with lang.using(language):
            said = {lang.say(f"page_{c}", site="s.example") for c in ("missing", "refused", "private", "unreachable")}
        assert len(said) == 4
