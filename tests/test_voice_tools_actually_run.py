"""Why every spoken command said "done" and did nothing.

The owner's report: she claims she added the reminder, played the sound, started
the brainstorm — and none of it happened. In weeks, exactly one thing ever
worked: the camera flash.

That one exception is the whole diagnosis. The flash is the only tool that
touches neither an account nor the database.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cloud"))

from app.api.voice_ws.tools import _build_system_instruction, _dispatch_tool  # noqa: E402


class _Recorder:
    """Stands in for the brain's voice dispatch and keeps who it was called for."""

    def __init__(self, result=None):
        self.chat_id = None
        self.result = result or {"handled": True, "ok": True, "reply": "تمام"}

    def __call__(self, name, args, chat_id):
        from app.utils.user_profiles import current_user_id
        self.chat_id, self.tenant = chat_id, current_user_id()
        return self.result


def test_tools_are_given_an_account():
    """The bug, in one assertion.

    The voice path once ran tools with no account: a reminder was written for a
    tenant called "default" — a real row no screen in the app can see. Nothing
    raised. The failure was a value, and values do not appear in logs.
    """
    rec = _Recorder()
    with patch("app.brain.voice.dispatch", rec):
        _dispatch_tool("schedule", {"text": "اتصل بأمي"}, "owner-42")
    assert rec.chat_id == "owner-42", (
        f"tools would write to {rec.chat_id!r} instead of the owner")
    assert rec.tenant == "owner-42", "the scoped stores would read and write nothing"


def test_an_exception_is_reported_as_failure_not_silence():
    def _boom(*_a):
        raise RuntimeError("mongo down")

    with patch("app.brain.voice.dispatch", _boom):
        out = _dispatch_tool("list_add", {"text": "x"}, "owner-42")
    assert out["handled"] is False and "فشل" in out["reply"]


def _instruction() -> str:
    """The prompt, without needing a database.

    `_build_system_instruction` also loads memory and the persona, which want
    Mongo. Those are not what these tests are about, and letting them fail here
    would report a database problem for a wording bug — the exact kind of
    misdirection this whole file exists because of.
    """
    with patch("app.api.voice_ws.tools._stm_chat_id", return_value="owner-42"), \
         patch("app.brain.persona.build_effective_persona",
               return_value="persona"), \
         patch("app.db.get_db", return_value=None):
        return _build_system_instruction()


def test_she_is_told_the_first_acknowledgement_is_not_a_confirmation():
    """The instruction that turned a broken tool into a lie.

    She is asked to say "hold on, turning it off" *before* running the tool, so
    the owner hears she was heard. Good — except that line comes out whether or
    not the tool then works, and it sounds exactly like completion. The prompt now
    separates the two and forbids claiming an action the tool did not report.
    """
    text = _instruction()
    assert "الإقرار الأول مش تأكيد تنفيذ" in text
    assert "ما رجعت الأداة إنه نجح" in text


def test_content_requests_are_exempt_from_the_two_sentence_limit():
    """"One or two sentences, execute and confirm without explaining."

    Right for "turn off the light". Wrong for a brainstorm or a summary — she ran
    the tool and went quiet, because the content *is* the answer and the rule
    forbade it.
    """
    text = _instruction()
    assert "عصف ذهني" in text and "المحتوى نفسه هو الجواب" in text
