"""The sites with an official connection (GitHub, Gmail, Google accounts, Facebook, Messenger,
Instagram) are read as anyone reads them, with no session: never a sign-in, a kept session or a
fill on them (`web_page.NO_SESSION`, `check_url(…, session=True)`). Payment pages stay never
opened at all. Refused in both languages as «no permission»."""
from __future__ import annotations

import pytest
from brain_fakes import A, brain_db  # noqa: F401
from test_browser_page import Resp, web  # noqa: F401
from test_browser_sites import _h, client, on  # noqa: F401

from app.brain import lang, tools
from app.brain.ctx import TurnCtx
from app.features import browser_job, browser_sites, web_page
from app.utils.user_profiles import active_user_profile_context

REPO = ("<html><head><title>me/robot</title></head><body><main><h1>me/robot</h1><p>"
        + "A public repository for a small desk robot, its firmware and its docs. " * 6
        + "</p></main></body></html>").encode()
SIGN_IN = (b"<html><body><form><input name='login'><input type='password' name='password'>"
           b"<button>Sign in</button></form></body></html>")


@pytest.mark.parametrize("url", ["https://github.com/me/robot", "https://gist.github.com/me/1",
                                 "https://www.facebook.com/somepage"])
def test_a_public_page_of_a_site_with_an_official_connection_is_read(web, url):  # noqa: F811
    host = web_page.site_of(url)
    web.hosts[host] = web.hosts["www." + host] = "93.184.216.34"
    web.pages[web_page.check_url(url)] = Resp(body=REPO)
    page = web_page.read(url, user_id="userA")
    assert "A public repository" in page["text"] and page["login"] is False


def test_its_sign_in_page_is_refused_with_no_link_to_sign_in(web):  # noqa: F811
    web.hosts["github.com"] = "93.184.216.34"
    web.pages["https://github.com/login"] = Resp(body=SIGN_IN)
    with pytest.raises(web_page.PageError) as e:
        web_page.read("https://github.com/login", user_id="userA")
    assert e.value.code == "no_session" and e.value.site == "github.com"


@pytest.mark.parametrize("url", ["https://github.com/settings", "https://mail.google.com/mail/u/0",
                                 "https://accounts.google.com/signin", "https://m.facebook.com/x",
                                 "https://www.instagram.com/x", "https://messenger.com/t/1"])
def test_a_session_on_them_is_never_opened(url, monkeypatch):
    from app.integrations import steel_client
    monkeypatch.setattr(steel_client, "create_session", lambda *a, **kw: pytest.fail("session"))
    with pytest.raises(web_page.PageError) as e:
        web_page.read_signed_in(url, {"cookies": []}, user_id="userA")
    assert e.value.code == "no_session"
    with pytest.raises(web_page.PageError):
        web_page.check_url(url, session=True)
    assert web_page.check_url(url)        # read publicly, it may be opened


@pytest.mark.parametrize("url", ["https://www.paypal.com/checkout", "https://checkout.stripe.com/c/x",
                                 "https://pay.google.com/"])
def test_payment_pages_are_never_opened_at_all(url, web):  # noqa: F811
    with pytest.raises(web_page.PageError) as e:
        web_page.read(url, user_id="userA")
    assert e.value.code == "blocked" and web.opened == []


def _tool(name, args, language, monkeypatch):
    monkeypatch.setenv("SANDY_FLAGS", '{"browser": ["userA"]}')
    with active_user_profile_context({**A, "chat_id": "userA"}), lang.using(language):
        return tools.execute(name, args, TurnCtx(user_id="userA", message="x"))


@pytest.mark.parametrize("language, words", [("ar", "ما عندي إذن"), ("en", "I don't have permission")])
def test_a_fill_on_them_is_refused_before_anything_opens(brain_db, monkeypatch, language, words):  # noqa: F811
    monkeypatch.setattr(browser_sites, "level", lambda site: browser_sites.SUBMIT)
    monkeypatch.setattr(browser_job, "start", lambda *a, **kw: pytest.fail("started"))
    result = _tool("page_fill", {"url": "https://github.com/me/robot/issues/new", "goal": "x"}, language, monkeypatch)
    assert result["ok"] is False and words in result["reply"] and "github.com" in result["reply"]


def test_a_fill_job_itself_refuses_them(brain_db):  # noqa: F811
    with pytest.raises(web_page.PageError) as e:
        browser_job.start({"url": "https://github.com/me/robot", "goal": "x"}, user_id="userA",
                          thread_id="t", language="ar")
    assert e.value.code == "no_session"


@pytest.mark.parametrize("language, words", [("ar", "ما عندي إذن"), ("en", "I don't have permission")])
def test_a_kept_session_on_them_is_never_used_for_a_read(brain_db, monkeypatch, language, words):  # noqa: F811
    monkeypatch.setattr(browser_sites, "session", lambda url: {"cookies": [{"name": "s", "value": "v"}]})
    monkeypatch.setattr(web_page, "read", lambda *a, **kw: pytest.fail("read"))
    result = _tool("page_read", {"url": "https://github.com/me/robot"}, language, monkeypatch)
    assert result["ok"] is False and words in result["reply"]


def test_the_app_keeps_no_sign_in_and_no_fill_level_for_them(client):  # noqa: F811
    r = client.post("/api/browser/sites/github.com/session", headers=_h(), json={"cookies": []})
    assert r.status_code == 400 and r.get_json()["error"] == "blocked"
    for level in ("fill", "submit"):
        r = client.patch("/api/browser/sites/github.com", headers=_h(), json={"level": level})
        assert r.status_code == 400 and r.get_json()["error"] == "blocked"
    assert client.patch("/api/browser/sites/github.com", headers=_h(), json={"level": "read"}).status_code == 200
