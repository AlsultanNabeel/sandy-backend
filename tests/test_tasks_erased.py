"""A task's memory and its results go with the account and with «امسح بياناتي», and only his."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from brain_fakes import A, B, brain_db  # noqa: F401

from app import notify
from app.blocks import tasks
from app.features import account_delete
from app.utils.user_profiles import active_user_profile_context

SPEC = {"instructions": "x", "notify_when": "y", "probe": {"tool": "recall", "args": {}},
        "tools": [], "lang": "en", "urgent": False}


def _a_task_with_memory_and_a_result(profile):
    with active_user_profile_context(profile):
        tid = tasks.add("t", SPEC, every_minutes=60,
                        first_at=datetime.now(timezone.utc) + timedelta(minutes=5))
        tasks.save_state(tid, {"fingerprint": "f", "last_result": "r"})
        notify.deliver(tid, "t", "r", "en")


@pytest.mark.parametrize("erase", ["delete", "wipe"])
def test_his_tasks_memory_and_results_go_and_the_others_stay(brain_db, monkeypatch, erase):  # noqa: F811
    monkeypatch.setattr(notify, "CHANNELS", [])
    for uid in ("userA", "userB"):
        brain_db["sandy_users"].insert_one({"_id": uid})
    _a_task_with_memory_and_a_result(A)
    _a_task_with_memory_and_a_result(B)
    r = (account_delete.delete_account if erase == "delete" else account_delete.wipe_account_data)("userA")
    assert r["ok"], r
    for name in ("sandy_task_state", "sandy_task_results", "sandy_schedules"):
        assert brain_db[name].count_documents({"user_id": "userA"}) == 0, name
        assert brain_db[name].count_documents({"user_id": "userB"}) == 1, name
