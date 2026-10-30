"""The app's Tasks screen (`api/tasks_api.py`): the tasks and their state, each one's results,
pause, resume and remove, and where results are emailed; behind the `tasks` switch, each user
seeing only his own, its words in his saved language."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from brain_fakes import A, B, brain_db  # noqa: F401

from app import notify
from app.blocks import tasks
from app.notify import mail
from app.utils.user_profiles import active_user_profile_context

SPEC = {"instructions": "check the gold price", "notify_when": "it moves 1%",
        "probe": {"tool": "web_search", "args": {"query": "gold price"}},
        "tools": ["web_search"], "lang": "en", "urgent": False}


@pytest.fixture()
def c(monkeypatch, brain_db):  # noqa: F811
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setenv("SANDY_FLAGS", '{"tasks": ["userA", "userB"]}')
    for k, v in {"SANDY_SMTP_USER": "s@gmail.com", "SANDY_SMTP_PASSWORD": "pw",
                 "SANDY_PUBLIC_URL": "https://sandy.example"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(notify, "CHANNELS", [])
    from app.api.server import create_app
    from app.features import usage_store
    monkeypatch.setattr(usage_store, "check_and_record", lambda *a, **k: None)
    return create_app(mongo_db=brain_db).test_client()


@pytest.fixture()
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(mail, "_post", lambda to, subject, body, html="": sent.append((to, subject, body)))
    return sent


def _h(uid="userA"):
    from app.api.auth_handlers import make_token
    return {"Authorization": f"Bearer {make_token('user', user_id=uid)}"}


def _task(profile=A, title="Gold"):
    with active_user_profile_context(profile):
        return tasks.add(title, SPEC, every_minutes=60,
                         first_at=datetime.now(timezone.utc) + timedelta(minutes=5))


def _result(task_id, body, profile=A, language="en"):
    with active_user_profile_context(profile):
        return notify.deliver(task_id, "Gold", body, language)


ROUTES = [("GET", "/api/scheduled-tasks"), ("GET", "/api/scheduled-tasks/x/results"), ("POST", "/api/scheduled-tasks/x/seen"),
          ("POST", "/api/scheduled-tasks/x/pause"), ("POST", "/api/scheduled-tasks/x/resume"),
          ("DELETE", "/api/scheduled-tasks/x"), ("GET", "/api/notify/email"),
          ("POST", "/api/notify/email"), ("DELETE", "/api/notify/email")]


@pytest.mark.parametrize("method,path", ROUTES)
def test_without_the_switch_there_is_no_such_screen(c, monkeypatch, method, path):
    monkeypatch.setenv("SANDY_FLAGS", '{"tasks": ["userB"]}')
    assert c.open(path, method=method, headers=_h(), json={}).status_code == 404


@pytest.mark.parametrize("method,path", ROUTES)
def test_signed_out_is_refused(c, method, path):
    assert c.open(path, method=method, json={}).status_code == 401


def test_the_list_shows_each_task_with_its_state_and_what_he_has_not_seen(c):
    tid = _task()
    _result(tid, "up 2%")
    _result(tid, "down 1%")
    with active_user_profile_context(A):
        tasks.save_state(tid, {"failures": 1, "last_error": "RuntimeError: down",
                               "last_result": "down 1%"})
    body = c.get("/api/scheduled-tasks", headers=_h()).get_json()
    [row] = body["tasks"]
    assert row["id"] == tid and row["title"] == "Gold" and row["status"] == "running"
    assert row["every_minutes"] == 60 and row["instructions"] == "check the gold price"
    assert row["unseen"] == 2 and row["failures"] == 1 and row["last_result"] == "down 1%"
    assert row["next_at"].endswith("+00:00")


def test_a_user_sees_and_touches_only_his_own_tasks(c):
    tid = _task(A)
    _result(tid, "secret", A)
    assert c.get("/api/scheduled-tasks", headers=_h("userB")).get_json()["tasks"] == []
    for method, path in [("GET", f"/api/scheduled-tasks/{tid}/results"), ("POST", f"/api/scheduled-tasks/{tid}/seen"),
                         ("POST", f"/api/scheduled-tasks/{tid}/pause"), ("DELETE", f"/api/scheduled-tasks/{tid}")]:
        assert c.open(path, method=method, headers=_h("userB")).status_code == 404, path
    assert c.get("/api/scheduled-tasks", headers=_h()).get_json()["tasks"][0]["status"] == "running"


def test_a_tasks_results_newest_first_and_seen_once_opened(c, brain_db):  # noqa: F811
    tid, other = _task(), _task(title="Stock")
    first = _result(tid, "up 2%")
    second = _result(tid, "down 1%")
    brain_db["sandy_task_results"].update_one(       # a millisecond apart is the same to Mongo
        {"_id": first}, {"$set": {"at": datetime(2026, 10, 29, 8, tzinfo=timezone.utc)}})
    _result(other, "milk low")
    rows = c.get(f"/api/scheduled-tasks/{tid}/results", headers=_h()).get_json()["results"]
    assert [r["id"] for r in rows] == [second, first] and rows[0]["body"] == "down 1%"
    assert rows[0]["seen"] is False and rows[0]["at"].endswith("+00:00")
    assert c.post(f"/api/scheduled-tasks/{tid}/seen", headers=_h()).get_json() == {"ok": True}
    listed = {t["title"]: t["unseen"] for t in c.get("/api/scheduled-tasks", headers=_h()).get_json()["tasks"]}
    assert listed == {"Gold": 0, "Stock": 1}


def test_pause_resume_and_remove(c):
    tid = _task()
    _result(tid, "up 2%")
    assert c.post(f"/api/scheduled-tasks/{tid}/pause", headers=_h()).get_json() == {"ok": True}
    assert c.get("/api/scheduled-tasks", headers=_h()).get_json()["tasks"][0]["status"] == "paused"
    c.post(f"/api/scheduled-tasks/{tid}/pause", headers=_h())             # again: still paused, no harm
    assert c.post(f"/api/scheduled-tasks/{tid}/resume", headers=_h()).get_json() == {"ok": True}
    assert c.get("/api/scheduled-tasks", headers=_h()).get_json()["tasks"][0]["status"] == "running"
    assert c.delete(f"/api/scheduled-tasks/{tid}", headers=_h()).get_json() == {"ok": True}
    assert c.get("/api/scheduled-tasks", headers=_h()).get_json()["tasks"] == []
    assert c.delete(f"/api/scheduled-tasks/{tid}", headers=_h()).status_code == 404
    with active_user_profile_context(A):
        assert notify.unseen() == []                            # its results went with it


@pytest.mark.parametrize("language", ["ar", "en"])
def test_an_unknown_task_is_404_with_a_message_in_his_language(c, brain_db, language):  # noqa: F811
    brain_db["sandy_users"].update_one({"_id": "userA"}, {"$set": {"language": language}},
                                       upsert=True)
    r = c.post("/api/scheduled-tasks/nope/pause", headers=_h())
    body = r.get_json()
    assert r.status_code == 404 and body["error"] == "not_found"
    from app.brain import lang
    assert bool(lang._ARABIC.search(body["message"])) == (language == "ar")


def test_the_email_is_set_confirmed_by_its_link_and_forgotten(c, outbox):
    assert c.get("/api/notify/email", headers=_h()).get_json() == {
        "address": "", "confirmed": False, "ready": True}
    r = c.post("/api/notify/email", headers=_h(), json={"address": "me@example.com"})
    assert r.get_json() == {"ok": True, "state": "sent"} and len(outbox) == 1
    token = outbox[0][2].split("t=")[1].split()[0]
    assert c.get("/api/notify/email", headers=_h()).get_json()["confirmed"] is False
    page = c.get(f"/api/notify/email/confirm?t={token}")
    assert page.status_code == 200 and page.mimetype == "text/html"
    done = c.post("/api/notify/email/confirm", data={"t": token})
    assert done.status_code == 200 and done.mimetype == "text/html"
    assert c.get("/api/notify/email", headers=_h()).get_json() == {
        "address": "me@example.com", "confirmed": True, "ready": True}
    assert c.post("/api/notify/email/confirm", data={"t": token}).status_code == 400   # once
    assert c.delete("/api/notify/email", headers=_h()).get_json() == {"ok": True}
    assert c.get("/api/notify/email", headers=_h()).get_json()["address"] == ""


@pytest.mark.parametrize("address,code,status", [("nope", "bad_address", 400),
                                                 ("a@b.com\nBcc: x@y.com", "bad_address", 400)])
def test_a_bad_address_is_refused_with_a_message(c, outbox, address, code, status):
    r = c.post("/api/notify/email", headers=_h(), json={"address": address})
    assert r.status_code == status and r.get_json()["error"] == code
    assert r.get_json()["message"].strip() and outbox == []


def test_without_the_mail_settings_the_app_is_told(c, outbox, monkeypatch):
    monkeypatch.delenv("SANDY_SMTP_PASSWORD")
    assert c.get("/api/notify/email", headers=_h()).get_json()["ready"] is False
    r = c.post("/api/notify/email", headers=_h(), json={"address": "me@example.com"})
    assert r.status_code == 503 and r.get_json()["error"] == "not_set_up"


def test_a_link_that_did_not_leave_is_said(c, monkeypatch):
    monkeypatch.setattr(mail, "_post", lambda *a: (_ for _ in ()).throw(OSError("smtp down")))
    r = c.post("/api/notify/email", headers=_h(), json={"address": "me@example.com"})
    assert r.status_code == 502 and r.get_json()["error"] == "not_sent"
    assert c.get("/api/notify/email", headers=_h()).get_json()["address"] == ""


def test_a_wrong_link_is_a_page_not_an_error(c):
    r = c.get("/api/notify/email/confirm?t=nope")
    assert r.status_code == 400 and r.mimetype == "text/html"
    r = c.post("/api/notify/email/confirm", data={"t": "nope"})
    assert r.status_code == 400 and r.mimetype == "text/html"


# Opening the link confirms nothing (review of phase one): a mail scanner or a preview opens
# links on its own. The page has a «Confirm» button, and only that confirms, in his language.
@pytest.mark.parametrize("language, button", [("ar", "أكّد"), ("en", "Confirm")])
def test_opening_the_link_shows_a_button_and_only_the_button_confirms(c, outbox, brain_db, language,  # noqa: F811
                                                                      button):
    c.get("/api/notify/email", headers=_h())
    brain_db["sandy_users"].update_one({"_id": "userA"}, {"$set": {"language": language}})
    c.post("/api/notify/email", headers=_h(), json={"address": "me@example.com"})
    token = outbox[0][2].split("t=")[1].split()[0]
    for _ in range(3):
        page = c.get(f"/api/notify/email/confirm?t={token}")
        assert page.status_code == 200 and button in page.get_data(as_text=True)
        assert 'method="post"' in page.get_data(as_text=True)
    assert c.get("/api/notify/email", headers=_h()).get_json()["confirmed"] is False
    assert c.post("/api/notify/email/confirm", data={"t": token}).status_code == 200
    assert c.get("/api/notify/email", headers=_h()).get_json()["confirmed"] is True


def test_asking_for_links_has_a_limit(c, outbox, monkeypatch):
    clock = [datetime(2026, 10, 29, 9, 0, tzinfo=timezone.utc)]
    monkeypatch.setattr(mail, "_now", lambda: clock[0])
    for n in range(mail.LINKS_A_DAY):
        r = c.post("/api/notify/email", headers=_h(), json={"address": f"me{n}@example.com"})
        assert r.get_json()["state"] == "sent"
        clock[0] += mail.RESEND_AFTER
    r = c.post("/api/notify/email", headers=_h(), json={"address": "more@example.com"})
    assert r.status_code == 429 and r.get_json()["error"] == "too_many"
    assert r.get_json()["message"].strip() and len(outbox) == mail.LINKS_A_DAY


# The public schedule routes on a task's row (review of phase one): they ask the switch as the
# Tasks screen does, and a delete takes what the task saw and its results with it.
@pytest.mark.parametrize("method, body", [("PATCH", {"status": "cancelled"}), ("DELETE", None)])
def test_the_schedule_routes_ask_the_switch_on_a_task(c, monkeypatch, method, body):
    tid = _task()
    monkeypatch.setenv("SANDY_FLAGS", "{}")
    r = c.open(f"/api/schedules/{tid}", method=method, json=body, headers=_h())
    assert r.status_code == 404
    with active_user_profile_context(A):
        assert tasks.get(tid)["status"] == "pending"


@pytest.mark.parametrize("language", ["en", "ar"])
def test_deleting_a_task_through_the_schedules_takes_its_state_and_results(c, language):
    tid = _task()
    with active_user_profile_context(A):
        tasks.save_state(tid, {"fingerprint": "f", "last_result": "Gold is up"})
    _result(tid, "Gold is up")
    r = c.delete(f"/api/schedules/{tid}", headers={**_h(), "X-Lang": language})
    assert r.status_code == 200
    with active_user_profile_context(A):
        assert tasks.get(tid) is None and tasks.state(tid) == {} and notify.of_task(tid) == []


def test_another_users_task_is_not_found_through_the_schedules(c):
    tid = _task()
    assert c.delete(f"/api/schedules/{tid}", headers=_h("userB")).status_code == 404
    with active_user_profile_context(A):
        assert tasks.get(tid)


# The email's two buttons (owner, 30 Oct): «افتح المهمة» opens it in the app, «وقّف التنبيهات»
# opens a page whose button pauses it; opening a link changes nothing (a mail scanner opens
# them), a link is signed for its task and its account alone, and the words are his language.
@pytest.mark.parametrize("language, open_word, stop_word", [("ar", "افتح المهمة", "وقّف التنبيهات"),
                                                            ("en", "Open the task", "Stop the alerts")])
def test_the_email_carries_open_and_stop_buttons(c, outbox, brain_db, monkeypatch, language,  # noqa: F811
                                                 open_word, stop_word):
    from types import SimpleNamespace as NS
    c.get("/api/notify/email", headers=_h())
    brain_db["sandy_users"].update_one({"_id": "userA"}, {"$set": {"language": language}})
    c.post("/api/notify/email", headers=_h(), json={"address": "me@example.com"})
    token = outbox[0][2].split("t=")[1].split()[0]
    c.post("/api/notify/email/confirm", data={"t": token})
    sent = []
    monkeypatch.setattr(mail, "_post", lambda to, subject, body, html="": sent.append(NS(body=body, html=html)))
    monkeypatch.setattr(notify, "CHANNELS", [mail.send])
    tid = _task()
    _result(tid, "Gold is up 2%", language=language)
    email = sent[-1]
    assert open_word in email.html and stop_word in email.html
    assert "/api/notify/task/open?t=" in email.body and "/api/notify/task/stop?t=" in email.body
    stop = email.body.split("/api/notify/task/stop?t=")[1].split()[0]
    opened = email.body.split("/api/notify/task/open?t=")[1].split()[0]
    r = c.get(f"/api/notify/task/open?t={opened}")
    assert r.status_code == 200 and f"sandy://tasks/{tid}" in r.get_data(as_text=True)
    page = c.get(f"/api/notify/task/stop?t={stop}")
    assert page.status_code == 200 and 'method="post"' in page.get_data(as_text=True)
    with active_user_profile_context(A):
        assert tasks.get(tid)["status"] == "pending"            # opening paused nothing
    assert c.post("/api/notify/task/stop", data={"t": stop}).status_code == 200
    with active_user_profile_context(A):
        assert tasks.get(tid)["status"] == "paused"


def test_a_forged_or_other_tasks_link_does_nothing(c):
    tid = _task()
    good = mail.task_link_token("userA", tid)
    for bad in ("nope", good[:-2] + "xx", mail.task_link_token("userB", tid)):
        assert c.post("/api/notify/task/stop", data={"t": bad}).status_code == 400
    with active_user_profile_context(A):
        assert tasks.get(tid)["status"] == "pending"
