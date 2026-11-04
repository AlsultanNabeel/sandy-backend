"""What a watched listing is made of (`web_page.extract` → `items`): its main repeated content, a
title and its link per block, read the same way on any site (blocks of the same shape side by
side, and in each the link whose words mean something), never its navigation, its menus, its
users, its actions (hide, vote, flag, reply, login, share) or a search of it elsewhere. Saved
pages: Hacker News, a store, an Arabic list and an English one."""
from __future__ import annotations

import pathlib
import re

import pytest
from bs4 import BeautifulSoup

from app.brain import lang, task_diff
from app.features import web_page

PAGES = pathlib.Path(__file__).parent / "fixtures" / "pages"


def _page(name, url):
    return web_page.extract((PAGES / name).read_bytes(), url)


def test_hacker_news_is_its_thirty_stories_and_nothing_else():
    raw = (PAGES / "hn_newest.html").read_bytes()
    titles = [a.get_text(" ", strip=True) for a in
              BeautifulSoup(raw, "html.parser").select("span.titleline > a")]
    items = _page("hn_newest.html", "https://news.ycombinator.com/newest")["items"]
    assert [i["title"] for i in items] == titles and len(items) == 30
    for i in items:
        assert not re.search(r"user\?id|hide\?id|vote\?id|from\?site|hn\.algolia\.com|/(past|front|newcomments|ask|"
                             r"show|jobs|submit|login)\b", i["url"]), i
        assert i["url"].startswith("https://")


def test_a_store_is_its_products():
    items = _page("store.html", "https://shop.example.com/c/audio")["items"]
    assert items == [{"title": t, "url": f"https://shop.example.com/p/{n}"} for n, t in [
        (101, "Wireless Earbuds Pro 2"), (102, "Noise Cancelling Headphones X"),
        (103, "Portable Bluetooth Speaker Mini"), (104, "Studio Monitor Speakers Pair"),
        (105, "USB-C Audio Adapter"), (106, "Kids Safe Volume Headphones")]]


def test_an_arabic_list_is_its_headlines():
    items = _page("list_ar.html", "https://news.example.ps/")["items"]
    assert [i["title"] for i in items] == [
        "إطلاق شريحة جديدة لإنترنت الأشياء بسعر منخفض", "جامعة بيرزيت تفتتح مختبراً للروبوتات",
        "تحديث أمني عاجل لأنظمة الهواتف الذكية", "كيف تختار حاسوباً محمولاً للدراسة",
        "شركات ناشئة فلسطينية في معرض دبي للتقنية", "دليل مبسّط للبرمجة بلغة بايثون"]
    assert all(i["url"].startswith("https://news.example.ps/a/") for i in items)


def test_an_english_list_is_its_posts_not_their_authors_votes_or_searches():
    items = _page("list_en.html", "https://reads.example.com/")["items"]
    assert [i["url"] for i in items] == [
        "https://blog.example.org/rust-embedded", "https://essays.example.net/quiet",
        "https://lab.example.com/sensors", "https://notes.example.io/sqlite", "https://www.example.edu/maps"]
    assert items[1]["title"] == "The case for quiet software"


def test_an_article_has_no_items_and_is_compared_by_its_words():
    article = ("<html><body><main><h1>Notes</h1>" + "<p>A long paragraph about the sea and the weather.</p>" * 6
               + "<p>See <a href='https://a.example/x'>this</a> and <a href='https://b.example/y'>that</a>.</p>"
               "</main></body></html>")
    page = web_page.extract(article, "https://notes.example/")
    assert page["items"] == []
    assert "text" in web_page.for_compare({**page, "warning": False})


def test_a_watched_listing_is_compared_by_its_items():
    page = _page("hn_newest.html", "https://news.ycombinator.com/newest")
    seen = web_page.for_compare({**page, "warning": False})
    assert seen["links"] == [{"title": i["title"], "url": i["url"]} for i in page["items"]]


@pytest.mark.parametrize("language", ["ar", "en"])
def test_how_things_are_now_names_the_real_items(language):
    page = _page("store.html", "https://shop.example.com/c/audio")
    with lang.using(language):
        line = task_diff.describe(web_page.for_compare({**page, "warning": False}))
    assert "«Wireless Earbuds Pro 2»" in line and "Add to cart" not in line and "Quick view" not in line
    assert lang.number(6) in line if language == "ar" else "6" in line
