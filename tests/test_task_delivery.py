"""How a task's results are emailed is what he said, never Sandy's choice (`blocks/tasks.py`
delivery, `notify/mail.py`): right away on every change, a summary once a day at his hour, or
at most once every N hours; with nothing said, at most once an hour. An account gets at most
`ACCOUNT_CAP` emails an hour, the last of them gathering the rest. The minute runner hands the
channels what they hold. The way is shown with the task before his yes, in both languages,
behind the `tasks` switch."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest
from brain_fakes import A, brain_db  # noqa: F401

from app import notify
from app.blocks import schedules, tasks
from app.brain import lang, tools
from app.brain.ctx import TurnCtx
from app.notify import mail
from app.utils.user_profiles import active_user_profile_context

SMTP = {"SANDY_SMTP_USER": "sandy@gmail.com", "SANDY_SMTP_PASSWORD": "app-password",
        "SANDY_PUBLIC_URL": "https://sandy.example"}
SPEC = {"instructions": "check gold", "notify_when": "it moves", "lang": "en", "urgent": False,
        "probe": {"tool": "web_search", "args": {"query": "gold"}}, "tools": ["web_search"]}
# Nine in the morning on his clock (no zone saved: the default one, UTC+2 in November).
NINE = datetime(2026, 11, 2, 7, 0, tzinfo=timezone.utc)


@pytest.fixture
def post(brain_db, monkeypatch):  # noqa: F811
    for k, v in SMTP.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("SANDY_FLAGS", '{"tasks": ["userA"]}')
    sent, clock = [], [NINE]
    monkeypatch.setattr(mail, "_post", lambda to, subject, body, html="": sent.append(
        NS(to=to, subject=subject, body=body, html=html)))
    monkeypatch.setattr(mail, "_now", lambda: clock[0])
    monkeypatch.setattr(notify, "CHANNELS", [mail.send])
    brain_db["sandy_users"].insert_one({"_id": "userA", "language": "en"})
    mail.ask_to_confirm("userA", "a@example.com")
    assert mail.confirm(sent.pop().body.split("t=")[1].split()[0]) == "userA"
    return NS(sent=sent, clock=clock, db=brain_db)


def _task(delivery=None, title="Gold"):
    with active_user_profile_context(A):
        spec = {**SPEC, **({"delivery": delivery} if delivery else {})}
        return tasks.add(title, spec, every_minutes=10, first_at=NINE + timedelta(days=30))


def _deliver(tid, body):
    with active_user_profile_context(A):
        return notify.deliver(tid, "Gold", body, "en")


def _flush():
    with active_user_profile_context(A):
        notify.flush()


def test_with_nothing_said_it_is_at_most_once_an_hour(post):
    tid = _task()
    _deliver(tid, "first")
    post.clock[0] += timedelta(minutes=30)
    _deliver(tid, "second")
    assert len(post.sent) == 1
    post.clock[0] += timedelta(minutes=31)
    _flush()
    assert len(post.sent) == 2 and "second" in post.sent[1].body


def test_right_away_sends_every_change(post):
    tid = _task({"mode": "instant"})
    for n in range(3):
        _deliver(tid, f"change {n}")
        post.clock[0] += timedelta(minutes=1)
    assert [("change %d" % n) in post.sent[n].body for n in range(3)] == [True] * 3


def test_a_daily_summary_goes_once_at_his_hour_with_all_of_the_day(post):
    tid = _task({"mode": "daily", "at": "21:00"})
    _deliver(tid, "morning news")
    post.clock[0] += timedelta(hours=3)
    _deliver(tid, "noon news")
    _flush()
    assert post.sent == []
    post.clock[0] = NINE + timedelta(hours=12)          # 21:00 on his clock
    _flush()
    _flush()
    assert len(post.sent) == 1
    assert "morning news" in post.sent[0].body and "noon news" in post.sent[0].body
    post.clock[0] += timedelta(minutes=30)
    _deliver(tid, "late news")
    assert len(post.sent) == 1                          # tomorrow's summary
    post.clock[0] += timedelta(days=1)
    _flush()
    assert len(post.sent) == 2 and "late news" in post.sent[1].body


def test_every_few_hours_is_at_most_that_often(post):
    tid = _task({"mode": "every", "hours": 3})
    _deliver(tid, "one")
    post.clock[0] += timedelta(hours=2)
    _deliver(tid, "two")
    _flush()
    assert len(post.sent) == 1
    post.clock[0] += timedelta(hours=1, minutes=1)
    _flush()
    assert len(post.sent) == 2 and "two" in post.sent[1].body


def test_an_account_gets_at_most_twenty_an_hour_and_the_last_gathers_the_rest(post, monkeypatch):
    ids = [_task({"mode": "instant"}, title=f"T{n}") for n in range(25)]
    real = mail.flush
    monkeypatch.setattr(mail, "flush", lambda: None)       # held, none sent yet
    with active_user_profile_context(A):
        for n, tid in enumerate(ids):
            notify.deliver(tid, f"T{n}", f"news {n}", "en")
    monkeypatch.setattr(mail, "flush", real)
    _flush()
    assert len(post.sent) == mail.ACCOUNT_CAP
    last = post.sent[-1].body
    assert all(f"news {n}" in last for n in range(mail.ACCOUNT_CAP - 1, 25))
    _deliver(ids[0], "one more")
    assert len(post.sent) == mail.ACCOUNT_CAP           # held: the hour is full
    post.clock[0] += timedelta(hours=1, minutes=1)
    _flush()
    assert len(post.sent) == mail.ACCOUNT_CAP + 1 and "one more" in post.sent[-1].body


def test_the_minute_runner_hands_the_channels_what_they_hold(post, monkeypatch):
    from app.services import schedule_runner
    tid = _task()
    _deliver(tid, "first")
    post.clock[0] += timedelta(minutes=10)
    _deliver(tid, "second")
    post.clock[0] += timedelta(minutes=51)
    schedule_runner.run_all_due(post.db)
    assert len(post.sent) == 2 and "second" in post.sent[1].body
    monkeypatch.setenv("SANDY_FLAGS", "{}")
    _deliver(tid, "third")
    post.clock[0] += timedelta(hours=2)
    schedule_runner.run_all_due(post.db)
    assert len(post.sent) == 2                          # the switch off: nothing goes


# ── by talk: shown before the yes, set when made or later ──

MOSTAQL = {"title": "Mostaql", "instructions": "check Mostaql for new projects", "every_minutes": 60,
           "check_tool": "web_search", "check_args": {"query": "mostaql"}, "notify_when": "a new one",
           "tools": ["web_search"]}


def _run(name, language, confirmed=False, **args):
    with active_user_profile_context(A), lang.using(language):
        ctx = TurnCtx(user_id="userA")
        ctx.confirmed = confirmed
        return tools.execute(name, args, ctx)


@pytest.mark.parametrize("language, args, said", [
    ("ar", {}, "بالكتير مرة بالساعة"),
    ("en", {}, "at most once an hour"),
    ("ar", {"notify_how": "instant"}, "فوراً كل ما يتغيّر"),
    ("en", {"notify_how": "instant"}, "right away whenever it changes"),
    ("ar", {"notify_how": "daily", "notify_at": "21:00"}, "ملخص مرة باليوم الساعة 21:00"),
    ("en", {"notify_how": "daily", "notify_at": "21:00"}, "a summary once a day at 21:00"),
    ("ar", {"notify_how": "every", "notify_hours": 3}, "بالكتير مرة كل 3 ساعات"),
    ("en", {"notify_how": "every", "notify_hours": 3}, "at most once every 3 hours"),
])
def test_the_way_is_shown_before_the_yes_and_kept(brain_db, monkeypatch, language, args, said):  # noqa: F811
    monkeypatch.setenv("SANDY_FLAGS", '{"tasks": ["userA"]}')
    asked = _run("task_create", language, **MOSTAQL, **args)
    assert asked.get("needs_confirmation") and said in asked["summary"]
    assert _run("task_create", language, confirmed=True, **MOSTAQL, **args)["ok"]
    with active_user_profile_context(A):
        [row] = tasks.running()
        assert tasks.how(row) == tasks.clean_delivery(args.get("notify_how"), args.get("notify_hours"),
                                                      args.get("notify_at"))
    assert said in _run("task_list", language)["reply"]


@pytest.mark.parametrize("language", ["ar", "en"])
def test_the_way_is_changed_by_talk(brain_db, monkeypatch, language):  # noqa: F811
    monkeypatch.setenv("SANDY_FLAGS", '{"tasks": ["userA"]}')
    _run("task_create", language, confirmed=True, **MOSTAQL)
    out = _run("task_update", language, match_text="Mostaql", notify_how="daily", notify_at="9:30")
    assert out["ok"]
    with active_user_profile_context(A):
        assert tasks.how(tasks.running()[0]) == {"mode": "daily", "at": "09:30"}


@pytest.mark.parametrize("args", [{"notify_how": "daily"}, {"notify_how": "daily", "notify_at": "25:00"},
                                  {"notify_how": "every", "notify_hours": 0}, {"notify_how": "sometimes"}])
def test_a_way_that_cannot_be_read_is_refused(brain_db, monkeypatch, args):  # noqa: F811
    monkeypatch.setenv("SANDY_FLAGS", '{"tasks": ["userA"]}')
    assert not _run("task_create", "en", confirmed=True, **MOSTAQL, **args)["ok"]
    with active_user_profile_context(A):
        assert tasks.running() == []


def test_the_default_is_kept_when_he_says_nothing(brain_db):  # noqa: F811
    with active_user_profile_context(A):
        tid = tasks.add("x", SPEC, every_minutes=60, first_at=NINE + timedelta(days=30))
        assert tasks.how(schedules.get(tid)) == {"mode": "every", "hours": 1}


# His words decide even when the model leaves the field out (the chat model put «فوراً» in what
# is worth telling): the way is read from the words the task keeps, never guessed.
@pytest.mark.parametrize("words, way", [
    ("كل ساعة شوفيلي سعر الدهب وبلّغيني فوراً كل ما يتغيّر", {"mode": "instant"}),
    ("Check gold every hour and tell me right away whenever it changes", {"mode": "instant"}),
    ("notify me immediately", {"mode": "instant"}),
    ("ابعتيلي ملخص مرة باليوم الساعة تسعة بالليل", {"mode": "daily", "at": "21:00"}),
    ("ابعتيلي ملخص الساعة 8 الصبح", {"mode": "daily", "at": "08:00"}),
    ("send me a daily summary at 9pm", {"mode": "daily", "at": "21:00"}),
    ("a summary once a day at 18:30", {"mode": "daily", "at": "18:30"}),
    ("بلّغيني بالكتير مرة كل تلات ساعات", {"mode": "every", "hours": 3}),
    ("بالكتير مرة كل ساعتين", {"mode": "every", "hours": 2}),
    ("tell me at most once every 4 hours", {"mode": "every", "hours": 4}),
    ("no more than once every two hours", {"mode": "every", "hours": 2}),
    ("كل ساعة شوفي مشاريع جديدة على مستقل وابعتيلي الجديد", None),
    ("Every hour, check Mostaql for new projects and send me the new ones", None),
    ("track this month's spending and tell me if I go over budget", None),
])
def test_the_way_is_read_from_his_words(words, way):
    from app.brain import tools_tasks
    assert tools_tasks.said_delivery(words) == way


@pytest.mark.parametrize("language, words, said", [
    ("ar", "كل ساعة شوفيلي سعر الدهب وبلّغيني فوراً كل ما يتغيّر", "فوراً كل ما يتغيّر"),
    ("en", "check gold every hour and tell me right away when it changes", "right away whenever it changes"),
])
def test_a_way_he_said_is_kept_when_the_model_left_it_out(brain_db, monkeypatch, language, words, said):  # noqa: F811
    monkeypatch.setenv("SANDY_FLAGS", '{"tasks": ["userA"]}')
    args = {**MOSTAQL, "instructions": words}
    assert said in _run("task_create", language, **args)["summary"]
    assert _run("task_create", language, confirmed=True, **args)["ok"]
    with active_user_profile_context(A):
        assert tasks.how(tasks.running()[0]) == {"mode": "instant"}


# The way he is told is never in what he is told (owner, 30 Oct): «فوراً» leaked into the text.
@pytest.mark.parametrize("language, words, way_word", [
    ("ar", "كل ساعة شوفيلي سعر الدهب وبلّغيني فوراً كل ما يتغيّر", "فورا"),
    ("en", "check gold every hour and tell me right away whenever it changes", "right away"),
])
def test_the_way_of_telling_never_reaches_the_message(brain_db, monkeypatch, language, words, way_word):  # noqa: F811
    from app.brain import task_runner
    monkeypatch.setenv("SANDY_FLAGS", '{"tasks": ["userA"]}')
    monkeypatch.setattr("app.features.research.web_results", lambda q: [{"title": "P1", "url": "u1"}])
    args = {**MOSTAQL, "instructions": words, "notify_when": "فوراً" if language == "ar" else "right away"}
    assert _run("task_create", language, confirmed=True, **args)["ok"]
    with active_user_profile_context(A):
        [row] = tasks.running()
    assert tasks.how(row) == {"mode": "instant"}
    assert way_word not in row["payload"]["notify_when"].replace("ً", "").lower()
    seen = task_runner._think_messages(row["payload"], {"added": [{"title": "P2", "url": "u2"}]}, {})
    shown = " ".join(m["content"] for m in seen).replace("ً", "").lower()
    assert way_word not in shown and "never say how or when" in shown
