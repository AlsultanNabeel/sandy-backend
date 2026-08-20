"""Three ways to reach Sandy, one memory.

The owner's test is the right one: ask her something out loud, then open the app
and ask a follow-up about the same thing. She should know what "it" is.

She did not. Not because anything was broken — every piece worked — but because
short-term memory is stored per conversation thread, and the three channels use
different threads:

    robot voice   -> /voice        -> thread = owner_id
    app voice     -> /voice        -> thread = owner_id      (same, correctly)
    app chat      -> /api/agent    -> thread = conversation_id

So the robot and the app's voice call already shared a memory. The app's text
chat had its own, and neither could see the other. Durable memory never had this
problem — it is keyed by person, not by thread — which is why she remembered
facts about him across channels but not the sentence he had just said.

These tests pin the fix: threads stay separate (a chat should not have another
chat's replies bleeding into it), and every channel can additionally see the
last few turns from anywhere.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cloud"))

_GRAPH = (Path(__file__).resolve().parent.parent
          / "cloud/app/agent/graph/graph.py").read_text(encoding="utf-8")
_VOICE_MEM = (Path(__file__).resolve().parent.parent
              / "cloud/app/api/voice_ws/memory.py").read_text(encoding="utf-8")


def test_a_turn_records_who_said_it_not_just_which_thread():
    """The key was `thread:user`, and a key is not a query.

    With the person's id only ever glued into a string, "everything this person
    said recently" could not be asked for at all. Storing `user_id` as a field
    is the whole enabling change.
    """
    assert '"user_id": str(user_id)' in _GRAPH, (
        "turns no longer record their owner, so cross-channel recall cannot work")


def test_the_voice_can_see_what_was_typed_in_the_app():
    from app.agent.graph.graph import recent_turns_for_user  # noqa: F401

    assert "recent_turns_for_user" in _VOICE_MEM, (
        "the voice path reads only its own thread again — the robot cannot "
        "remember a conversation the owner had in the app a minute ago")
    assert "_stm_load(chat_id, chat_id)" in _VOICE_MEM, (
        "the fallback for pre-existing documents is gone; anyone whose memory "
        "was written before this deploy starts from nothing")


def test_the_app_chat_can_see_what_was_said_out_loud():
    assert "cross = recent_turns_for_user(user_id" in _GRAPH, (
        "the text chat is blind to the voice channel again — this is the "
        "owner's exact complaint, in the other direction")


def test_the_same_sentence_is_not_shown_twice():
    """The thread's own turns are also in the cross-channel read.

    Without a guard, the last thing said appears twice in the context — once as
    background, once as history. A model reading that has good reason to think
    it was said twice, and will answer as if it was.
    """
    assert "seen = {(m.get(\"role\"), m.get(\"content\")) for m in history}" in _GRAPH


def test_threads_are_not_merged():
    """Sharing recent turns is not the same as merging conversations.

    The easy fix would have been to drop `conversation_id` and put everything in
    one thread. That trades one bug for a worse one: separate chats would run
    into each other, and a long thread would push the current topic out of a ten
    message window. Each channel keeps its own transcript; only a short shared
    view is added on top.
    """
    assert "thread_id = str(conversation_id or chat_id)" in _GRAPH, (
        "per-conversation threading was removed — chats will now bleed into "
        "each other")
    assert "limit: int = 6" in _GRAPH, (
        "the shared window is unbounded or missing; it is meant to be a few "
        "turns of background, not a second transcript")


def test_the_voice_prompt_actually_contains_the_recent_turns():
    """Sharing the turns is worthless if the prompt then drops them.

    The owner's test, run for real: he asked the robot "what do you know about
    me" and got a good answer — durable facts. He asked the app "what was the
    last thing I asked you" and got a good answer — that thread's own history.
    He went back to the robot and asked the same thing: "I don't know."

    She did know. `_voice_memory_context` builds with `durable_only=True`, which
    keeps stable facts and throws the recent lines away before they reach the
    prompt. That was a deliberate guard against the native-audio model reading a
    logged line and continuing it as if it had just been said.

    But the guard already exists in words, further down the prompt — "this is a
    past record, do not reply to it" — so the lines can come back and the
    protection stays.
    """
    tools = (Path(__file__).resolve().parent.parent
             / "cloud/app/api/voice_ws/tools.py").read_text(encoding="utf-8")

    assert "elif rich_ctx is None:" not in tools, (
        "recent turns are a fallback again — they are only loaded when the rich "
        "context FAILS, which is exactly the bug: on the working path she has "
        "facts about him and no idea what he just said")
    assert "سجلّ سابق للاطّلاع فقط" in tools, (
        "the 'do not reply to the record' instruction is gone. It is the only "
        "reason it is safe to seed recent turns into a native-audio model")


def test_every_turn_remembers_which_body_said_it():
    """He can ask "when did I tell you that?" and the answer should be real.

    Three doors, one memory — but a person remembers *where* a conversation
    happened. "You told me on the phone" and "you told me while standing here"
    are different memories, and without the tag she can only say "you told me",
    which is the kind of answer that makes her feel like software.
    """
    assert 'history.append({"role": "user", "content": user_msg, "timestamp": ts, "via": via})' in _GRAPH

    session = (Path(__file__).resolve().parent.parent
               / "cloud/app/api/voice_ws/session.py").read_text(encoding="utf-8")
    assert 'set_voice_channel("الروبوت")' in session, (
        "the robot no longer tags its turns — it and the app's call share a "
        "socket, so without this they become indistinguishable in the record")
    assert 'set_voice_channel("مكالمة التطبيق")' in session

    assert 'f"[{via}] {role_label}: {content}"' in _VOICE_MEM, (
        "the source is recorded but never shown to her, which is the same as "
        "not recording it")


def test_she_knows_your_name_on_every_channel():
    """He typed his name at first open. She asked him who he was anyway.

    The onboarding answers — preferred name, interests — were saved correctly
    and read by a function that resolved the user from the *ambient request
    profile*. The chat has one, so it worked there. The voice path builds its
    system prompt with no profile open, so the same function returned nothing,
    and the robot greeted its owner like a stranger.

    Nothing was broken and nothing was missing. One reader was standing
    somewhere it could not see, and which channel you used decided whether she
    knew you.

    Passing the id in removes the question entirely.
    """
    import inspect

    from app.agent.context_builder import get_onboarding_directive

    sig = inspect.signature(get_onboarding_directive)
    assert "user_id" in sig.parameters, (
        "the onboarding profile is read from ambient context again — it will "
        "silently return nothing on the voice path")

    ctx = (Path(__file__).resolve().parent.parent
           / "cloud/app/agent/context_builder.py").read_text(encoding="utf-8")
    assert "get_onboarding_directive(chat_id)" in ctx, (
        "the caller stopped passing the user, so the parameter is decoration")


def test_durable_memory_was_always_keyed_by_person():
    """Stated so the next reader does not 'fix' the part that was right.

    Semantic long-term memory is searched by chat_id — the person — not by
    conversation. That is why she could recall facts about him from any channel
    while forgetting what he said thirty seconds ago on another one, which made
    the bug read like something much stranger than it was.
    """
    ctx = (Path(__file__).resolve().parent.parent
           / "cloud/app/agent/context_builder.py").read_text(encoding="utf-8")
    assert "search_relevant_summaries(message, chat_id" in ctx
