"""«هلّق بزبطلك الهدف» — and then nothing was saved.

He asked her to add a reading goal and the reply said she was about to do it,
and stopped. A wrong tool shows itself the moment she answers; a promise is only
discovered later, when he goes looking for a goal that was never written, and by
then he has no reason to think anything failed.

The rule is narrow: she may say she cannot, and she may ask what he means. She
may not describe an action that did not happen.
"""
from __future__ import annotations


def test_the_rule_rides_in_every_persona():
    """It is appended by code, after the tone, so a custom persona or a Heroku
    override cannot drop it — the same reason the language rule lives there."""
    from app.brain.persona import NO_PROMISES_RULE, build_effective_persona

    persona = build_effective_persona(None)
    assert NO_PROMISES_RULE in persona


def test_a_custom_persona_cannot_replace_it(monkeypatch):
    from app.brain.persona import NO_PROMISES_RULE, build_effective_persona
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
    from app.brain.persona import NO_PROMISES_RULE

    for phrase in ("هلّق بزبطلك", "رح أضيفه", "بسجّله إلك"):
        assert phrase in NO_PROMISES_RULE

    # And it has to tell her what to do instead, or she just goes quiet.
    assert "ما قدرتي تنفّذي" in NO_PROMISES_RULE


def test_the_identity_lock_still_has_the_last_word():
    """Ordering is load-bearing: the lock is appended last so nothing a user
    writes can sit after it. Adding a rule must not change that."""
    from app.config import SANDY_IDENTITY_LOCK
    from app.brain.persona import build_effective_persona

    persona = build_effective_persona(None)
    assert persona.rstrip().endswith(SANDY_IDENTITY_LOCK.rstrip())
