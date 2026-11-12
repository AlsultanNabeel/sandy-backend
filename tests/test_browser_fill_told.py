"""Every way a fill ends is told in the chat he asked from, in his language, with why: a fill
cut by a restart (`close_held`) or whose holder died (`sweep`, «lost») writes its own message
there too, once, not only the ones that ended in their own thread. On 12 Nov he heard nothing
of a fill and asked «شو صار بالتعبئة؟»."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from brain_fakes import brain_db  # noqa: F401

from app.features import browser_job
from app.integrations import steel_client

C7 = "c7" * 16


@pytest.fixture
def db(monkeypatch, brain_db):  # noqa: F811
    monkeypatch.setattr(steel_client, "release", lambda sid, seconds=0, timeout=None: True)
    monkeypatch.setattr(steel_client, "closed", lambda sid, **kw: True, raising=False)
    return brain_db


def _row(db, language, **more):
    old = datetime.now(timezone.utc) - timedelta(minutes=10)
    row = {"_id": "job-1", "user_id": "userA", "site": "httpbin.org", "status": browser_job.RUNNING,
           "steel_id": "st1", "thread_id": C7, "lang": language, "detached": True, "beat_at": old,
           "closed_at": None, "created_at": old, "updated_at": old, **more}
    db[browser_job.COLLECTION].insert_one(row)
    return row


def _said(db):
    chat = db["conversations"].find_one({"_id": C7}) or {}
    return [m["text"] for m in chat.get("messages") or []]


@pytest.mark.parametrize("language, words", [("ar", "السيرفر عم يعيد تشغيله"), ("en", "server is restarting")])
def test_a_fill_cut_by_a_restart_is_told_in_his_chat(db, monkeypatch, language, words):
    row = _row(db, language)
    monkeypatch.setattr(browser_job, "_HELD", {"job-1": {"row": row, "user_id": "userA"}})
    browser_job.close_held()
    said = _said(db)
    assert len(said) == 1 and words in said[0] and "httpbin.org" in said[0]


@pytest.mark.parametrize("language, words", [("ar", "الشغل اللي كان ماسكها وقف"), ("en", "work holding it stopped")])
def test_a_fill_whose_holder_died_is_told_in_his_chat_once(db, language, words):
    _row(db, language)
    browser_job.sweep()
    browser_job.sweep()
    said = _said(db)
    assert len(said) == 1 and words in said[0]
    assert db[browser_job.COLLECTION].find_one({"_id": "job-1"})["reason"] == "lost"


def test_a_fill_that_ended_already_is_not_told_again_by_the_sweep(db):
    _row(db, "en", status=browser_job.DONE)
    browser_job.sweep()
    assert _said(db) == []
