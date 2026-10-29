"""What a task tells is the difference the code computed, never the model's reading of two
snapshots (owner, 30 Oct 2026): he added «رمان» and the email said «انضاف ليمون», he added
«بطيخ» and it said «برتقال صار تم». His shopping list was longer than the thirty rows the
check read, so the new item was cut off and the window moved; the model was handed the two
windows and named what entered it. Now the check reads the whole list, the code computes
what changed (rows by their id, search results by title and link, text by paragraph,
numbers before and after), a simple list is told by a template with no model, the model
only explains a computed change, and a message naming anything outside it is not sent."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest
from brain_fakes import A, brain_db  # noqa: F401

from app import notify
from app.blocks import items, schedules, tasks
from app.brain import background, task_diff, task_runner
from app.utils.user_profiles import active_user_profile_context

FRUIT = ["تفاح", "موز", "ليمون", "برتقال", "عنب", "خوخ", "مشمش", "كرز", "تين", "جوافة",
         "مانجا", "كيوي", "أناناس", "فراولة", "توت", "دراق", "إجاص", "بلح", "جزر", "خيار",
         "بندورة", "بصل", "توم", "فلفل", "كوسا", "باذنجان", "بطاطا", "خس", "بقدونس", "نعنع",
         "ملفوف", "زهرة"]


@pytest.fixture
def world(brain_db, monkeypatch):  # noqa: F811
    monkeypatch.setenv("SANDY_FLAGS", '{"tasks": ["userA"]}')
    sent, asked = [], []
    monkeypatch.setattr(notify, "CHANNELS", [lambda r: sent.append((r["task_id"], r["body"]))])

    def call(what, messages, **kw):        # a model that would name anything it was shown
        asked.append((what, messages))
        return NS(choices=[NS(message=NS(content="انضاف ليمون", tool_calls=None))])
    monkeypatch.setattr(background, "call", call)
    with active_user_profile_context(A):
        for n, fruit in enumerate(FRUIT):
            iid = items.add("shopping", fruit)
            if n % 3 == 0:
                items.update(iid, done=True)
    return NS(sent=sent, asked=asked)


def _task(title):
    spec = {"instructions": "تابعي قائمة التسوق وقلّيلي شو انضاف", "notify_when": "شي جديد",
            "probe": {"tool": "recall", "args": {"list": "shopping"}}, "tools": ["recall"],
            "lang": "ar", "urgent": True}
    with active_user_profile_context(A):
        tid = tasks.add(title, spec, every_minutes=1,
                        first_at=datetime.now(timezone.utc) + timedelta(minutes=1))
        return schedules.get(tid)


def _run(doc):
    with active_user_profile_context(A):
        return task_runner.run(doc, "userA")


def test_what_happened_on_his_list_is_what_is_told_by_both_tasks(world):
    first, second = _task("التسوق"), _task("القائمة")
    _run(first), _run(second)                       # where each starts
    with active_user_profile_context(A):
        items.add("shopping", "رمان")
    _run(first), _run(second)
    with active_user_profile_context(A):
        bid = items.add("shopping", "بطيخ")
    _run(first), _run(second)
    bodies = [b for _, b in world.sent]
    assert bodies == ["انضاف «رمان» لـ«shopping»"] * 2 + ["انضاف «بطيخ» لـ«shopping»"] * 2
    assert not any("ليمون" in b or "برتقال" in b for b in bodies)
    assert world.asked == []                        # a simple list is told with no model
    with active_user_profile_context(A):
        items.update(bid, done=True)
    _run(first)
    assert world.sent[-1][1] == "«بطيخ» صار تم"


def test_nothing_changed_is_nothing_told(world):
    doc = _task("التسوق")
    for _ in range(5):
        _run(doc)
    assert world.sent == []


# ── the difference, the same for any source ──

def test_rows_are_compared_by_their_id():
    before = {"rows": [{"id": "1", "text": "تفاح", "done": False}, {"id": "2", "text": "موز", "done": False}]}
    now = {"rows": [{"id": "2", "text": "موز", "done": True}, {"id": "3", "text": "رمان", "done": False}]}
    d = task_diff.compute(before, now)
    assert [r["text"] for r in d["added"]] == ["رمان"]
    assert [r["text"] for r in d["removed"]] == ["تفاح"]
    assert [(c["after"]["text"], c["fields"]) for c in d["changed"]] == [("موز", ["done"])]


def test_search_results_are_compared_by_title_and_link():
    before = {"results": [{"title": "P1", "url": "u1", "text": "2 min ago"}]}
    now = {"results": [{"title": "P2", "url": "u2", "text": "new"}, {"title": "P1", "url": "u1", "text": "9 min ago"}]}
    d = task_diff.compute(before, now)
    assert [r["title"] for r in d["added"]] == ["P2"] and d["removed"] == [] and d["changed"] == []


def test_text_is_compared_by_paragraph():
    d = task_diff.compute("أول فقرة\n\nتاني فقرة", "أول فقرة\n\nفقرة جديدة")
    assert d["paragraphs_added"] == ["فقرة جديدة"] and d["paragraphs_removed"] == ["تاني فقرة"]


def test_numbers_are_compared_before_and_after():
    d = task_diff.compute({"spending": {"total": 120, "count": 4}, "to": "x"},
                          {"spending": {"total": 180, "count": 5}, "to": "y"})
    assert {(n["what"], n["before"], n["after"]) for n in d["numbers"]} == {
        ("spending.total", 120, 180), ("spending.count", 4, 5)}


def test_an_empty_difference_is_empty():
    assert task_diff.empty(task_diff.compute({"rows": [{"id": "1", "text": "a"}]},
                                             {"rows": [{"id": "1", "text": "a"}]}))


# ── the guard: a message naming what did not change is not sent ──

@pytest.mark.parametrize("message, ok", [
    ("انضاف «رمان» لقائمة التسوق", True),
    ("انضاف ليمون", False),
    ("برتقال صار تم", False),
    ("رمان new on the list", True),
])
def test_a_message_naming_what_did_not_change_is_not_sent(message, ok):
    before = {"rows": [{"id": "1", "text": "ليمون", "done": False}, {"id": "2", "text": "برتقال", "done": True}]}
    now = {"rows": [*before["rows"], {"id": "3", "text": "رمان", "done": False}]}
    d = task_diff.compute(before, now)
    assert task_diff.faithful(message, d, before, now) is ok


@pytest.mark.parametrize("language, said", [("ar", "انضاف «رمان» لـ«shopping»"),
                                            ("en", "«رمان» was added to «shopping»")])
def test_a_simple_list_is_told_by_a_template_in_his_language(language, said):
    from app.brain import lang
    d = task_diff.compute({"rows": []}, {"rows": [{"id": "3", "list": "shopping", "text": "رمان", "done": False}]})
    with lang.using(language):
        assert task_diff.template(d) == said
