"""A watched page's items in the email (`notify/mail.py`): each one a link whose words are its
title (`<a href>`, the raw address never shown in the HTML), a title in the other script kept in
its own direction (`dir="auto"` and `<bdi>`), at most `mail.MAX_ITEMS` (fifteen), then «and N
more» linking to the task. The template builds the links from the result's structured items
(title, url) and escapes every word; nothing a model wrote goes in as HTML or as Markdown. A
watch of a listing is told by the code (`task_diff.page_body`), never in the model's words."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest
from brain_fakes import A, brain_db  # noqa: F401

from app import notify
from app.blocks import schedules, tasks
from app.brain import background, lang, task_diff, task_runner
from app.features import web_page
from app.notify import mail
from app.utils.user_profiles import active_user_profile_context

AT = datetime(2026, 11, 4, 16, 45, tzinfo=timezone.utc)
OPEN = "https://sandy.example/api/notify/task/open?t=tok"


@pytest.fixture
def links(monkeypatch):
    monkeypatch.setattr(mail, "_links", lambda row: (OPEN, "https://sandy.example/api/notify/task/stop?t=tok"))


def _rows(language, items, body=None):
    with lang.using(language):
        made = body if body is not None else task_diff.page_body(items, "news.example")
    return [{"task_id": "t1", "title": "News", "body": made, "state": "", "at": AT, "lang": language,
             "items": items, "notes": []}]


def _compose(language, rows):
    with active_user_profile_context(A), lang.using(language):
        return mail._compose(rows)


EN_TITLES = [{"op": "added", "title": "Running Rust on a microcontroller", "url": "https://blog.example.org/rust"},
             {"op": "added", "title": "The case for quiet software", "url": "https://essays.example.net/quiet?a=1&b=2"}]
AR_TITLES = [{"op": "added", "title": "جامعة بيرزيت تفتتح مختبراً للروبوتات", "url": "https://news.example.ps/a/2"},
             {"op": "added", "title": "تحديث أمني عاجل للهواتف", "url": "https://news.example.ps/a/3"}]


def _anchors(page):
    return re.findall(r'<a href="([^"]+)"[^>]*>(.*?)</a>', page)


@pytest.mark.parametrize("language, items, side", [("ar", EN_TITLES, "rtl"), ("en", AR_TITLES, "ltr")])
def test_each_item_is_a_link_by_its_title_in_its_own_direction(brain_db, links, language, items, side):  # noqa: F811
    _, plain, page = _compose(language, _rows(language, items))
    assert f'dir="{side}"' in page
    for item in items:
        href = item["url"].replace("&", "&amp;")
        assert f'<a href="{href}" dir="auto"><bdi>{item["title"]}</bdi></a>' in page
        # The address is only ever the link's own, never shown as words.
        assert page.count(href) == 1 and f">{href}<" not in page
    assert "](" not in page and "](" not in plain and "[" not in page


@pytest.mark.parametrize("language, more", [("ar", "و٥ كمان"), ("en", "and 5 more")])
def test_past_fifteen_it_says_how_many_more_and_links_the_task(brain_db, links, language, more):  # noqa: F811
    items = [{"op": "added", "title": f"Story number {i}", "url": f"https://news.example/s/{i}"} for i in range(20)]
    _, plain, page = _compose(language, _rows(language, items))
    stories = [a for a in _anchors(page) if a[0].startswith("https://news.example/s/")]
    assert len(stories) == mail.MAX_ITEMS == 15
    assert f'<a href="{OPEN}"' in page and more in page and more in plain


def test_every_word_is_escaped_and_only_a_web_address_is_a_link(brain_db, links):  # noqa: F811
    items = [{"op": "added", "title": "<script>alert(1)</script> & co", "url": "https://x.example/1"},
             {"op": "added", "title": "Bad link here", "url": "javascript:alert(1)"}]
    _, _, page = _compose("en", _rows("en", items))
    assert "<script>" not in page and "&lt;script&gt;alert(1)&lt;/script&gt; &amp; co" in page
    assert "javascript:" not in page and "Bad link here" in page


@pytest.mark.parametrize("language", ["ar", "en"])
def test_a_models_markdown_never_reaches_the_email(brain_db, links, language):  # noqa: F811
    rows = [{"task_id": "t1", "title": "News", "at": AT, "lang": language, "state": "",
             "body": "**New:** [Quiet software](https://essays.example.net/quiet) and <b>more</b>"}]
    _, plain, page = _compose(language, rows)
    for out in (plain, page):
        assert "](" not in out and "**" not in out and "Quiet software" in out
    assert "<b>more</b>" not in page and "&lt;b&gt;more&lt;/b&gt;" in page


# ── The task that watches a listing ──

def _feed(rows):
    return ("<html><body><main><h1>Latest</h1>" + "".join(
        f"<div class='post'><a href='https://feed.example/p/{i}'>{t}</a></div>" for i, t in rows)
        + "</main></body></html>")


def test_a_watched_listing_is_told_by_the_code_with_its_items(brain_db, monkeypatch):  # noqa: F811
    monkeypatch.setenv("SANDY_FLAGS", '{"tasks": ["userA"], "browser": ["userA"]}')
    stories = [(i, f"Story number {i} here") for i in range(1, 6)]
    page = {"html": _feed(stories)}

    def fetch(url):
        return web_page.check_url(url), "text/html", page["html"].encode()
    monkeypatch.setattr(web_page, "_fetch_html", fetch)
    monkeypatch.setattr(web_page.config, "STEEL_API_KEY", "")
    monkeypatch.setattr(background, "call", lambda what, messages, **kw: NS(choices=[NS(message=NS(
        content="Here: [Fourth](https://evil.example/)", tool_calls=None))]))
    kept = []
    monkeypatch.setattr(notify, "CHANNELS", [lambda r: kept.append(r)])
    with active_user_profile_context(A), lang.using("en"):
        spec = {"instructions": "watch the feed", "notify_when": "new stories", "lang": "en", "urgent": False,
                "probe": {"tool": "page_read", "args": {"url": "https://feed.example/"}}, "tools": ["page_read"]}
        tid = tasks.add("feed", spec, every_minutes=60, first_at=datetime.now(timezone.utc) + timedelta(minutes=1))
        task_runner.start(tid, "userA")
        page["html"] = _feed([(6, "Fourth story here"), *stories])
        task_runner.run(schedules.get(tid), "userA")
    [row] = kept
    assert row["items"] == [{"op": "added", "title": "Fourth story here", "url": "https://feed.example/p/6"}]
    assert "evil.example" not in json.dumps(row, default=str) and "](" not in row["body"]
    assert "«Fourth story here»" in row["body"] and "Source: feed.example" in row["body"]
