"""The email channel (`app/notify/mail.py`): nothing before the address is confirmed by its link,
one email per task an hour at most with the rest gathered into the next, the words around it
in the user's saved language, and how it leaves only the settings."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest
from brain_fakes import A, B, brain_db  # noqa: F401

from app import notify
from app.notify import mail
from app.utils.user_profiles import active_user_profile_context

SMTP = {"SANDY_SMTP_HOST": "smtp.gmail.com", "SANDY_SMTP_USER": "sandy@gmail.com",
        "SANDY_SMTP_PASSWORD": "app-password", "SANDY_PUBLIC_URL": "https://sandy.example"}


@pytest.fixture
def post(brain_db, monkeypatch):  # noqa: F811
    """The settings in place, the clock in our hands, every email kept instead of sent."""
    for k, v in SMTP.items():
        monkeypatch.setenv(k, v)
    sent, clock = [], [datetime(2026, 10, 29, 9, 0, tzinfo=timezone.utc)]
    monkeypatch.setattr(mail, "_post", lambda to, subject, body, html="": sent.append(
        NS(to=to, subject=subject, body=body, html=html)))
    monkeypatch.setattr(mail, "_now", lambda: clock[0])
    monkeypatch.setattr(notify, "CHANNELS", [mail.send])
    for uid in ("userA", "userB"):
        brain_db["sandy_users"].insert_one({"_id": uid, "language": "ar"})
    return NS(sent=sent, clock=clock, db=brain_db)


def _confirmed(post, uid="userA", address="a@example.com"):
    mail.ask_to_confirm(uid, address)
    link = post.sent.pop()
    token = link.body.split("t=")[1].split()[0]
    assert mail.confirm(token) == uid
    return address


def _deliver(task="t1", body="new", profile=A):
    with active_user_profile_context(profile):
        return notify.deliver(task, "Mostaql", body, "en")


def test_nothing_is_emailed_before_the_address_is_confirmed(post):
    mail.ask_to_confirm("userA", "a@example.com")
    assert len(post.sent) == 1 and "t=" in post.sent[0].body     # only the link
    _deliver()
    _deliver(task="t2")
    assert len(post.sent) == 1
    assert mail.status("userA") == {"address": "a@example.com", "confirmed": False, "ready": True}


def test_the_link_confirms_once_and_a_wrong_or_old_one_never(post):
    mail.ask_to_confirm("userA", "a@example.com")
    token = post.sent[0].body.split("t=")[1].split()[0]
    assert mail.confirm("nope") is None
    post.clock[0] += mail.LINK_LIVES + timedelta(minutes=1)
    assert mail.confirm(token) is None
    assert mail.status("userA")["confirmed"] is False
    mail.ask_to_confirm("userA", "a@example.com")
    token = post.sent[-1].body.split("t=")[1].split()[0]
    assert mail.confirm(token) == "userA"
    assert mail.confirm(token) is None                           # used once
    assert mail.status("userA")["confirmed"] is True


def test_one_email_an_hour_per_task_and_the_rest_gathered_into_the_next(post):
    _confirmed(post)
    _deliver(body="first")
    assert [s.to for s in post.sent] == ["a@example.com"] and "first" in post.sent[0].body
    post.clock[0] += timedelta(minutes=20)
    _deliver(body="second")
    post.clock[0] += timedelta(minutes=20)
    _deliver(body="third")
    assert len(post.sent) == 1                                   # held inside the hour
    post.clock[0] += timedelta(minutes=21)
    _deliver(body="fourth")
    assert len(post.sent) == 2
    assert all(w in post.sent[1].body for w in ("second", "third", "fourth"))
    assert "first" not in post.sent[1].body


def test_what_is_held_goes_out_on_the_next_flush_after_the_hour(post):
    _confirmed(post)
    _deliver(body="first")
    post.clock[0] += timedelta(minutes=10)
    _deliver(body="second")
    with active_user_profile_context(A):
        notify.flush()
        assert len(post.sent) == 1                               # still inside the hour
        post.clock[0] += timedelta(minutes=51)
        notify.flush()
        notify.flush()
    assert len(post.sent) == 2 and "second" in post.sent[1].body


def test_each_task_has_its_own_hour(post):
    _confirmed(post)
    _deliver(task="t1", body="gold")
    _deliver(task="t2", body="stock")
    assert len(post.sent) == 2


@pytest.mark.parametrize("language,word", [("ar", "ساندي"), ("en", "Sandy")])
def test_the_email_is_in_the_users_saved_language(post, language, word):
    post.db["sandy_users"].update_one({"_id": "userA"}, {"$set": {"language": language}})
    mail.ask_to_confirm("userA", "a@example.com")
    link = post.sent[-1]
    assert word in link.subject + link.body
    mail.confirm(link.body.split("t=")[1].split()[0])
    _deliver(body="the result")
    email = post.sent[-1]
    assert word in email.subject + email.body and "the result" in email.body
    other = "Sandy" if language == "ar" else "ساندي"
    assert other not in email.subject


def test_another_users_address_never_gets_a_result(post):
    _confirmed(post, "userB", "b@example.com")
    _deliver(profile=A)
    assert post.sent == []
    _deliver(profile=B)
    assert [s.to for s in post.sent] == ["b@example.com"]


def test_asking_again_soon_sends_no_second_link_and_another_address_waits(post):
    mail.ask_to_confirm("userA", "a@example.com")
    assert mail.ask_to_confirm("userA", "a@example.com") == "pending"
    assert len(post.sent) == 1
    with pytest.raises(ValueError, match="too_soon"):
        mail.ask_to_confirm("userA", "other@example.com")
    post.clock[0] += mail.RESEND_AFTER
    assert mail.ask_to_confirm("userA", "other@example.com") == "sent"
    assert post.sent[-1].to == "other@example.com"


def test_a_confirmed_address_asked_again_sends_nothing(post):
    _confirmed(post)
    assert mail.ask_to_confirm("userA", "A@Example.com ") == "confirmed"
    assert post.sent == []


@pytest.mark.parametrize("address", ["", "nope", "a@b", "a@example.com\nBcc: x@y.com",
                                     "a b@example.com", "x" * 250 + "@example.com"])
def test_a_bad_address_is_refused(post, address):
    with pytest.raises(ValueError, match="bad_address"):
        mail.ask_to_confirm("userA", address)
    assert post.sent == []


def test_without_the_settings_nothing_is_asked_or_sent(post, monkeypatch):
    _confirmed(post)
    monkeypatch.delenv("SANDY_SMTP_PASSWORD")
    assert mail.status("userA")["ready"] is False
    with pytest.raises(RuntimeError, match="not_set_up"):
        mail.ask_to_confirm("userA", "new@example.com")
    _deliver()
    assert post.sent == []


def test_a_send_that_fails_keeps_the_result_for_the_next_email(post, monkeypatch):
    _confirmed(post)
    real = mail._post

    def down(*a):
        raise OSError("smtp down")
    monkeypatch.setattr(mail, "_post", down)
    rid = _deliver(body="kept")
    with active_user_profile_context(A):
        assert [r["id"] for r in notify.unseen()] == [rid]
    monkeypatch.setattr(mail, "_post", real)
    with active_user_profile_context(A):
        notify.flush()
    assert len(post.sent) == 1 and "kept" in post.sent[0].body


def test_forgetting_the_address_stops_the_emails(post):
    _confirmed(post)
    mail.forget("userA")
    assert mail.status("userA") == {"address": "", "confirmed": False, "ready": True}
    _deliver()
    assert post.sent == []


@pytest.mark.parametrize("port,secure", [("587", "starttls"), ("465", "ssl")])
def test_how_it_leaves_is_the_settings(monkeypatch, port, secure):
    """Gmail now, a sending service on our own domain later: the same settings, other values."""
    for k, v in SMTP.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("SANDY_SMTP_PORT", port)
    monkeypatch.setenv("SANDY_EMAIL_FROM", "Sandy <hello@sandy.app>")
    done = []

    class Server:
        def __init__(self, host, port, timeout=None, context=None):
            done.append(("open", host, port, "ssl" if context and port == 465 else "plain"))
            assert timeout and timeout <= mail.TIMEOUT_S

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, context=None):
            done.append(("starttls",))

        def login(self, user, password):
            done.append(("login", user, password))

        def send_message(self, msg):
            done.append(("send", msg["From"], msg["To"], msg["Subject"]))

    monkeypatch.setattr(mail.smtplib, "SMTP", Server)
    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", Server)
    mail._post("a@example.com", "Hi", "Body")
    assert ("open", "smtp.gmail.com", int(port), "ssl" if secure == "ssl" else "plain") in done
    assert (("starttls",) in done) == (secure == "starttls")
    assert ("login", "sandy@gmail.com", "app-password") in done
    assert ("send", "Sandy <hello@sandy.app>", "a@example.com", "Hi") in done


# A limit on links (review of phase one): at most LINKS_A_DAY in a day, whatever the address,
# and forgetting the address does not start the count again.
def test_links_a_day_are_limited_and_forgetting_does_not_reset_them(post):
    for n in range(mail.LINKS_A_DAY):
        assert mail.ask_to_confirm("userA", f"a{n}@example.com") == "sent"
        mail.forget("userA")
        post.clock[0] += mail.RESEND_AFTER
    with pytest.raises(ValueError, match="too_many"):
        mail.ask_to_confirm("userA", "late@example.com")
    assert mail.ask_to_confirm("userB", "b@example.com") == "sent"     # his own count
    post.clock[0] += mail.LINKS_WINDOW
    assert mail.ask_to_confirm("userA", "late@example.com") == "sent"


def test_a_link_is_alive_until_used_and_reading_it_uses_nothing(post):
    mail.ask_to_confirm("userA", "a@example.com")
    token = post.sent[-1].body.split("t=")[1].split()[0]
    assert mail.link_owner(token) == "userA" and mail.link_owner(token) == "userA"
    assert mail.confirm(token) == "userA"
    assert mail.link_owner(token) is None and mail.link_owner("nope") is None


# The settings filled by hand later (the owner's, 29 Oct): while the user or the password is
# still CHANGE_ME, nothing is asked or sent, and Gmail is never tried with it.
@pytest.mark.parametrize("name", ["SANDY_SMTP_USER", "SANDY_SMTP_PASSWORD"])
def test_a_placeholder_setting_sends_nothing(post, monkeypatch, name):
    _confirmed(post)
    monkeypatch.setenv(name, "CHANGE_ME")
    assert mail.ready() is False and mail.status("userA")["ready"] is False
    with pytest.raises(RuntimeError, match="not_set_up"):
        mail.ask_to_confirm("userB", "b@example.com")
    _deliver(body="held back")
    assert post.sent == []


# The subject says what is new (owner, 30 Oct): «ساندي: انضاف «ليمون» لـ«shopping»», and with
# more than one, the newest and how many more.
@pytest.mark.parametrize("language, one, more", [
    ("ar", "ساندي: انضاف «ليمون» لـ«shopping»", "ساندي: انضاف «بطيخ» لـ«shopping» وكمان 1"),
    ("en", "Sandy: «lemon» was added to «shopping»", "Sandy: «melon» was added to «shopping» and 1 more"),
])
def test_the_subject_says_what_is_new(post, language, one, more):
    post.db["sandy_users"].update_one({"_id": "userA"}, {"$set": {"language": language}})
    _confirmed(post)
    first = one.split(": ", 1)[1]
    _deliver(body=first)
    assert post.sent[-1].subject == one
    post.clock[0] += timedelta(minutes=10)
    _deliver(body="held one")
    post.clock[0] += timedelta(minutes=10)
    _deliver(body=more.split(": ", 1)[1].rsplit(" وكمان", 1)[0].rsplit(" and 1 more", 1)[0])
    post.clock[0] += timedelta(hours=1)
    with active_user_profile_context(A):
        notify.flush()
    assert post.sent[-1].subject == more


# The body (owner, 30 Oct): what changed, when, and how things are now in a line, in his
# language and right to left in Arabic.
@pytest.mark.parametrize("language, at_word, now_word", [("ar", "الساعة", "هلّق:"), ("en", "At", "Now:")])
def test_the_body_says_what_changed_when_and_how_things_are_now(post, language, at_word, now_word):
    post.db["sandy_users"].update_one({"_id": "userA"}, {"$set": {"language": language}})
    _confirmed(post)
    with active_user_profile_context(A):
        notify.deliver("t1", "Mostaql", "انضاف «رمان» لـ«shopping»", language,
                       state="21 لسا و11 تم" if language == "ar" else "21 open and 11 done")
    body = post.sent[-1].body
    assert "انضاف «رمان» لـ«shopping»" in body and at_word in body and now_word in body
    lines = [ln for ln in body.splitlines() if ln.strip()]
    assert all(ln.startswith("‏") for ln in lines) == (language == "ar")


@pytest.mark.parametrize("language, body, shown", [
    ("ar", 'انضاف "رمان" و“بطيخ” للقائمة', "انضاف «رمان» و«بطيخ» للقائمة"),
    ("en", 'New project "Logo design" posted', "New project «Logo design» posted"),
])
def test_quotes_are_guillemets(post, language, body, shown):
    post.db["sandy_users"].update_one({"_id": "userA"}, {"$set": {"language": language}})
    _confirmed(post)
    _deliver(body=body)
    email = post.sent[-1]
    assert shown in email.body and shown in email.subject
    assert '"' not in email.body + email.subject and "“" not in email.body


# A simple, tidy email in Sandy's colours with a plain-text copy (owner, 30 Oct): right to left
# in Arabic, every word of his escaped.
@pytest.mark.parametrize("language, direction", [("ar", "rtl"), ("en", "ltr")])
def test_the_email_has_a_tidy_html_part_and_a_plain_one(post, language, direction):
    post.db["sandy_users"].update_one({"_id": "userA"}, {"$set": {"language": language}})
    _confirmed(post)
    _deliver(body="انضاف «رمان» <b>bold</b>")
    email = post.sent[-1]
    assert f'dir="{direction}"' in email.html and f'lang="{language}"' in email.html
    assert "#0077B6" in email.html and "&lt;b&gt;bold&lt;/b&gt;" in email.html
    assert "<b>bold</b>" in email.body                 # the plain copy is the words as they are
    assert "انضاف «رمان»" in email.html


def test_both_parts_leave_together(monkeypatch):
    for k, v in SMTP.items():
        monkeypatch.setenv(k, v)
    sent = []

    class Server:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, context=None):
            pass

        def login(self, user, password):
            pass

        def send_message(self, msg):
            sent.append(msg)
    monkeypatch.setattr(mail.smtplib, "SMTP", Server)
    mail._post("a@example.com", "Sandy: hi", "plain words", "<p>html words</p>")
    msg = sent[0]
    assert msg.get_content_type() == "multipart/alternative"
    assert [p.get_content_type() for p in msg.iter_parts()] == ["text/plain", "text/html"]
