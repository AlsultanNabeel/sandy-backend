"""What change a task tells (`tasks.changes_of`, kept with the task): `new` for news and feeds,
only what is new, never what dropped off the page, nor what comes back after it dropped (what it
saw is remembered, `task_diff.SEEN_MAX` rows and `SEEN_DAYS` days at most); `all` for lists,
prices and states, what was added, removed and changed. Sandy proposes it, the code guesses it
from his words when she did not, and the yes before it is saved names it. In both languages."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest
from brain_fakes import A, brain_db  # noqa: F401

from app import notify
from app.blocks import schedules, tasks
from app.brain import background, lang, task_diff, task_runner, tools
from app.brain.ctx import TurnCtx
from app.features import web_page
from app.utils.user_profiles import active_user_profile_context


@pytest.fixture
def on(monkeypatch, brain_db):  # noqa: F811
    monkeypatch.setenv("SANDY_FLAGS", '{"tasks": ["userA"], "browser": ["userA"]}')


def _feed(rows):
    return ("<html><body><main><h1>Latest</h1>" + "".join(
        f"<div class='post'><a href='https://feed.example/p/{r.replace(' ', '-')}'>{r} story</a></div>"
        for r in rows) + "</main></body></html>")


@pytest.fixture
def world(on, monkeypatch):
    pages = {"https://feed.example/": _feed(["alpha", "bravo", "charlie", "delta", "echo"])}

    def fetch(url):
        url = web_page.check_url(url)
        return url, "text/html", pages[url].encode()
    monkeypatch.setattr(web_page, "_fetch_html", fetch)
    monkeypatch.setattr(web_page.config, "STEEL_API_KEY", "")
    handed, sent = [], []

    def model(what, messages, **kw):
        if what == "task":
            handed.append(json.loads(messages[-1]["content"])["changed"])
        return NS(choices=[NS(message=NS(content=f"news {len(handed)}", tool_calls=None))])
    monkeypatch.setattr(background, "call", model)
    monkeypatch.setattr(notify, "CHANNELS", [lambda r: sent.append(r["body"])])
    return NS(pages=pages, handed=handed, sent=sent)


def _task(changes):
    with active_user_profile_context(A):
        spec = {"instructions": "watch the feed", "notify_when": "anything", "lang": "en", "urgent": False,
                "probe": {"tool": "page_read", "args": {"url": "https://feed.example/"}}, "tools": ["page_read"],
                **({"changes": changes} if changes else {})}
        tid = tasks.add("feed", spec, every_minutes=60, first_at=datetime.now(timezone.utc) + timedelta(minutes=1))
        task_runner.start(tid, "userA")
        return schedules.get(tid)


def _tick(world, doc, rows):
    world.pages["https://feed.example/"] = _feed(rows)
    with active_user_profile_context(A):
        return task_runner.run(doc, "userA")


def _titles(changed, key):
    return sorted(r.get("title") for r in changed.get(key) or [])


def test_new_only_tells_what_is_new_and_not_what_dropped_off(world):
    doc = _task(tasks.NEW)
    _tick(world, doc, ["foxtrot", "alpha", "bravo", "charlie", "delta"])        # echo dropped off
    assert len(world.handed) == 1
    assert _titles(world.handed[0], "added") == ["foxtrot story"] and not world.handed[0].get("removed")


def test_new_only_never_tells_one_that_comes_back(world):
    doc = _task(tasks.NEW)
    _tick(world, doc, ["foxtrot", "alpha", "bravo", "charlie", "delta"])
    _tick(world, doc, ["echo", "foxtrot", "alpha", "bravo", "charlie"])          # echo is back
    assert len(world.handed) == 1 and len(world.sent) == 1


def test_every_change_tells_what_was_added_and_removed(world):
    doc = _task(tasks.ALL)
    _tick(world, doc, ["foxtrot", "alpha", "bravo", "charlie", "delta"])
    assert _titles(world.handed[0], "added") == ["foxtrot story"]
    assert _titles(world.handed[0], "removed") == ["echo story"]


def test_a_task_without_it_tells_every_change(world):
    doc = _task(None)
    with active_user_profile_context(A):
        assert tasks.changes_of(schedules.get(str(doc["id"]))) == tasks.ALL


def test_what_it_saw_is_kept_within_its_bounds():
    now = datetime(2026, 11, 4, tzinfo=timezone.utc)
    old = {"k1": (now - timedelta(days=31)).isoformat(), "k2": (now - timedelta(days=2)).isoformat()}
    rows = {"links": [{"title": f"t{i}", "url": f"https://x.example/{i}"} for i in range(600)]}
    kept = task_diff.remember(rows, old, now)
    assert len(kept) == task_diff.SEEN_MAX == 500 and "k1" not in kept
    assert len(task_diff.remember({"links": rows["links"][:3]}, old, now)) == 4      # k2 and the three


def _create(args, language):
    with active_user_profile_context({**A, "chat_id": "userA"}), lang.using(language):
        return tools.execute("task_create", args, TurnCtx(user_id="userA", message=args["instructions"]))


BASE = {"title": "feed", "every_minutes": 60, "check_tool": "page_read",
        "check_args": {"url": "https://feed.example/"}}


@pytest.mark.parametrize("language, changes, words", [
    ("ar", "new", "عن الجديد بس"), ("en", "new", "only about what's new"),
    ("ar", "all", "أي إضافة أو إزالة أو تغيير"), ("en", "all", "anything added, removed or changed")])
def test_the_yes_before_saving_names_the_kind_of_change(world, language, changes, words):
    result = _create({**BASE, "instructions": "watch the feed", "changes": changes}, language)
    assert result.get("needs_confirmation") and words in result["summary"]


@pytest.mark.parametrize("words, kind", [
    ("تابعي آخر الأخبار على هالموقع", "new"), ("watch the newest posts on this feed", "new"),
    ("راقبي سعر هالمنتج", "all"), ("track whether it is in stock", "all"), ("watch this page", "all")])
def test_left_out_it_is_guessed_from_his_words(world, words, kind):
    from app.brain import tools_tasks
    assert tools_tasks.said_changes(words) == kind


def test_it_is_kept_with_the_task_and_changed_by_talk(world):
    with active_user_profile_context({**A, "chat_id": "userA"}), lang.using("en"):
        ctx = TurnCtx(user_id="userA", message="watch the newest posts", confirmed=True)
        made = tools.execute("task_create", {**BASE, "instructions": "watch the newest posts"}, ctx)
        assert made["ok"] and tasks.changes_of(schedules.get(made["id"])) == tasks.NEW
        changed = tools.execute("task_update", {"id": made["id"], "changes": "all"}, TurnCtx(user_id="userA"))
        assert changed["ok"] and "anything added, removed or changed" in changed["reply"]
        assert tasks.changes_of(schedules.get(made["id"])) == tasks.ALL
