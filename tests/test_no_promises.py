"""«هلّق بزبطلك الهدف» — and then nothing was saved.

He asked her to add a reading goal. `goal_set` is registered and the router
picked the chat tool anyway, so the reply came from the path that has no hands
at all — and that reply said she was about to do it, and stopped.

Two bugs, and this file is about the second one, which is the worse of the two.
A wrong tool shows itself the moment she answers. A promise is only discovered
later, when he goes looking for a goal that was never written, and by then he
has no reason to think anything failed.

The rule is narrow: she may say she cannot, and she may ask what he means. She
may not describe an action that did not happen.
"""
from __future__ import annotations


def test_the_rule_rides_in_every_persona():
    """It is appended by code, after the tone, so a custom persona or a Heroku
    override cannot drop it — the same reason the language rule lives there."""
    from app.agent.context_builder import NO_PROMISES_RULE, build_effective_persona

    persona = build_effective_persona(None)
    assert NO_PROMISES_RULE in persona


def test_a_custom_persona_cannot_replace_it(monkeypatch):
    from app.agent.context_builder import NO_PROMISES_RULE, build_effective_persona
    from app.features import users_store

    monkeypatch.setattr(
        users_store, "get_persona",
        lambda uid: {"custom_instructions": "احكي معي بالإنجليزي وبس", "dialect": "gulf"})

    persona = build_effective_persona("u1")
    assert "احكي معي بالإنجليزي وبس" in persona
    assert NO_PROMISES_RULE in persona, "a custom tone dropped the honesty rule"


def test_it_names_the_exact_phrases_that_went_wrong():
    """A rule the model has to infer is a rule it will not follow. These are the
    words she actually used."""
    from app.agent.context_builder import NO_PROMISES_RULE

    for phrase in ("هلّق بزبطلك", "رح أضيفه", "بسجّله إلك"):
        assert phrase in NO_PROMISES_RULE

    # And it has to tell her what to do instead, or she just goes quiet.
    assert "ما قدرتي تنفّذي" in NO_PROMISES_RULE


def test_the_identity_lock_still_has_the_last_word():
    """Ordering is load-bearing: the lock is appended last so nothing a user
    writes can sit after it. Adding a rule must not change that."""
    from app.config import SANDY_IDENTITY_LOCK
    from app.agent.context_builder import build_effective_persona

    persona = build_effective_persona(None)
    assert persona.rstrip().endswith(SANDY_IDENTITY_LOCK.rstrip())


def test_the_goal_tools_are_actually_in_the_catalogue():
    """The routing half. If `goal_set` were missing, no prompt rule would help —
    she would be honestly unable to do it, forever.

    Registration, not `bootstrap()`: the full startup wants a database and a
    model deployment, which CI has neither of — and what is being checked here
    is the catalogue, not the environment.
    """
    from app.agent.tools.registry import get_registry
    from app.agent.tools.setup import register_all_tools

    register_all_tools()
    names = set(get_registry().all_names())
    assert {"goal_set", "goal_list", "goal_done"} <= names
