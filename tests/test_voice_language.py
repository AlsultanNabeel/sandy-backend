"""On the call she answers in the speaker's language, as in chat: the tools' replies and the
honesty check's correction come in the language the turn was spoken in, else the last
turn's, else the user's own (independent review, 29 Oct 2026: they were always Arabic)."""
from __future__ import annotations

import asyncio

import pytest
from brain_fakes import brain_db  # noqa: F401
from test_brain_honesty import _call, _content, _Gemini

from app.brain import honesty, lang
from app.brain.voice import dispatch
from app.utils.user_profiles import active_user_profile_context
from brain_fakes import A

NS = __import__("types").SimpleNamespace


class _Spoken(_Gemini):
    """One turn: what she heard (before or after the tool call), a tool call, what she said."""

    def __init__(self, heard, said, tool=("confirm", {"answer": "yes"}), heard_first=False):
        super().__init__(tool)
        self.heard, self.said, self.heard_first = heard, said, heard_first
        self.outputs = []

    async def send_tool_response(self, function_responses):
        self.outputs += [r.response["output"] for r in function_responses]
        self.answered.set()

    async def receive(self):
        self.turns += 1
        if self.turns > 1:
            self.done.set()
            await asyncio.sleep(3600)
        if self.heard_first:
            yield _content(input_transcription=NS(text=self.heard))
        yield NS(server_content=None, go_away=None, session_resumption_update=None,
                 tool_call=NS(function_calls=[NS(id="1", name=self.tool[0], args=self.tool[1])]))
        await self.answered.wait()
        if not self.heard_first:
            yield _content(input_transcription=NS(text=self.heard))
        yield _content(output_transcription=NS(text=self.said))
        yield _content(turn_complete=True)


@pytest.mark.parametrize("saved, heard, said", [
    ("ar", "شيلي الحليب", "حذفت الحليب من القائمة"),
    ("en", "remove the milk", "I deleted the milk from the list"),
])
def test_voice_tools_and_correction_come_in_the_users_language(monkeypatch, brain_db,  # noqa: F811
                                                               saved, heard, said):
    monkeypatch.setattr(lang, "for_user", lambda uid: saved)
    gemini = _Spoken(heard, said)
    notes = _call(monkeypatch, gemini)
    assert gemini.outputs == [lang.PHRASES["voice_nothing_held"][saved]]
    assert len(notes) == 1
    assert notes[0]["turns"][0].parts[0].text == honesty.voice_correction(said, [], saved)
    assert lang.of(notes[0]["turns"][0].parts[0].text) == saved


@pytest.mark.parametrize("saved, heard, want", [
    ("en", "شيلي الحليب", "ar"),
    ("ar", "remove the milk please", "en"),
])
def test_voice_what_was_heard_before_the_tool_wins(monkeypatch, brain_db,  # noqa: F811
                                                   saved, heard, want):
    monkeypatch.setattr(lang, "for_user", lambda uid: saved)
    gemini = _Spoken(heard, "", heard_first=True)
    _call(monkeypatch, gemini)
    assert gemini.outputs == [lang.PHRASES["voice_nothing_held"][want]]


@pytest.mark.parametrize("language", ["ar", "en"])
def test_voice_confirm_replies_are_phrases(brain_db, language):  # noqa: F811
    with active_user_profile_context(A), lang.using(language):
        out = dispatch("confirm", {"answer": "yes"}, "userA")
    assert out["reply"] == lang.PHRASES["voice_nothing_held"][language]


@pytest.mark.parametrize("language", ["ar", "en"])
def test_voice_correction_in_both_languages(language):
    fix = honesty.voice_correction("حذفت الحليب" if language == "ar" else "I deleted the milk",
                                   [], language)
    assert fix and lang.of(fix) == language
    assert honesty.voice_correction("I deleted it", ["list_delete"], language) is None
