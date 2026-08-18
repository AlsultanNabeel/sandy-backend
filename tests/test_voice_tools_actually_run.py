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
    """Stands in for the dispatcher and keeps the context it was handed."""

    def __init__(self, result=None):
        self.ctx = None
        self.result = result or {"handled": True, "reply": "تمام"}

    def dispatch(self, name, args, ctx):
        self.ctx = ctx
        return self.result


def test_tools_are_given_an_account_and_a_database():
    """The bug, in one assertion.

    The voice path built its context with `state` and `mongo_db` left at their
    defaults. Tools read `ctx.state["chat_id"]` and `ctx.mongo_db`, so a reminder
    was written for an account called "default" — a real row, in a tenant no
    screen in the app can see — and anything needing the database got None and
    stopped.

    Nothing raised. The failure was a value, and values do not appear in logs.
    """
    rec = _Recorder()
    with patch("app.api.voice_ws.tools._stm_chat_id", return_value="owner-42"), \
         patch("app.db.get_db", return_value={"marker": True}):
        _dispatch_tool(rec, "reminder_create", {"text": "اتصل بأمي"})

    assert rec.ctx is not None, "the dispatcher was never called"
    assert rec.ctx.state, "tools were handed no state — chat_id falls back to 'default'"
    assert rec.ctx.state.get("chat_id") == "owner-42", (
        f"tools would write to {rec.ctx.state.get('chat_id')!r} instead of the "
        "owner — data lands in a tenant nothing can read back")
    assert rec.ctx.mongo_db is not None, (
        "tools that need the database get None and return without doing anything")


def test_the_camera_flash_is_the_exception_that_proves_it():
    """The one thing that worked needs neither of the two missing pieces.

    Kept as a test because the reasoning is the useful part: when one feature out
    of eighty works, the question is what that one does differently — and the
    answer named the bug faster than reading any of the other seventy-nine.
    """
    src = (Path(__file__).resolve().parent.parent
           / "cloud/app/agent/tools/schemas/device_tools.py").read_text(encoding="utf-8")
    body = src[src.index("def device_control"):src.index("def device_control") + 2000]

    assert "ctx.state" not in body and "ctx.mongo_db" not in body, (
        "device_control now depends on context the voice path may not supply — "
        "it was the only tool that still worked, and this is why")


def test_a_failed_tool_is_reported_as_failed():
    """`handled=False` must not reach the model looking like success.

    The dispatcher returns `handled=False` when it refuses or cannot find the
    tool, and only `reply` was passed on. Gemini saw a sentence, assumed it
    worked, and confirmed. That is half the "she says she did it" report.
    """
    rec = _Recorder({"handled": False, "reply": "ما لقيت هالجهاز."})
    with patch("app.api.voice_ws.tools._stm_chat_id", return_value="owner-42"), \
         patch("app.db.get_db", return_value={}):
        out = _dispatch_tool(rec, "device_control", {"device": "غير موجود"})

    assert out["handled"] is False
    assert "فشل" in out["reply"], (
        "the model is told a sentence with no sign of failure, so it will "
        "confirm an action that did not happen")


def test_an_exception_is_reported_as_failure_not_silence():
    class _Boom:
        def dispatch(self, *_):
            raise RuntimeError("mongo down")

    with patch("app.api.voice_ws.tools._stm_chat_id", return_value="owner-42"), \
         patch("app.db.get_db", return_value={}):
        out = _dispatch_tool(_Boom(), "task_create", {"title": "x"})

    assert out["handled"] is False and out["reply"]


def _instruction() -> str:
    """The prompt, without needing a database.

    `_build_system_instruction` also loads memory and the persona, which want
    Mongo. Those are not what these tests are about, and letting them fail here
    would report a database problem for a wording bug — the exact kind of
    misdirection this whole file exists because of.
    """
    with patch("app.api.voice_ws.tools._stm_chat_id", return_value="owner-42"), \
         patch("app.agent.context_builder.build_effective_persona",
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

    Right for "turn off the light". Wrong for "start a brainstorm" — she ran the
    tool and went quiet, because the content *is* the answer and the rule forbade
    it. Not a missing capability: a rule that removed it.
    """
    text = _instruction()
    assert "عصف ذهني" in text and "المحتوى نفسه هو الجواب" in text
