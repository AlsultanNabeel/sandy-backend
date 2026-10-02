"""Regression tests for the security/correctness hardening waves.

Locks in the fixes so they can't silently regress:
- unified Arabic yes/no confirmation matching (the "اه" → hallucinated حذفت bug),
- per-user pending-state key isolation,
- device transport validation (reserved node namespace).
"""

from app.brain.confirm import answer
from app.brain.pending import _key as pending_key
from app.features.device_store import _valid_transport


# ── confirmation matching ────────────────────────────────────────────────────

def test_confirmations_recognized():
    for t in ["اه", "آه", "أه", "اه صح", "اه احذفها", "اه 👍", "تمام", "نعم",
              "ايوه", "احذفها", "ok", "okay", "تمام يلا", "تمام لا مشكلة"]:
        assert answer(t) == "yes", t


def test_cancellations_recognized_and_win_mixed():
    for t in ["لا", "لأ", "مش هلأ", "الغي", "خلص", "no", "cancel", "لا تحذف",
              "اه بس لا"]:
        assert answer(t) == "no", t


def test_non_answers_are_ignored_not_confirmed():
    for t in ["شو الطقس اليوم", "اي واحدة", "احكيلي قصة", ""]:
        assert answer(t) == "other", t


# ── pending-state key isolation ──────────────────────────────────────────────

def test_pending_key_is_tenant_scoped():
    # Two users sharing a client-supplied conversation_id must not collide.
    assert pending_key("userA", "default") != pending_key("userB", "default")
    assert pending_key("userA", "default") == "userA:default"


# ── device transport validation ──────────────────────────────────────────────

def test_transport_rejects_reserved_node_namespace():
    # A raw mqtt topic must not target the ownership-checked node namespace.
    assert _valid_transport({"kind": "mqtt", "topic": "sandy/node/x/relay"}) is False
    # A normal room topic and a proper node transport are fine.
    assert _valid_transport({"kind": "mqtt", "topic": "room/cmd/light"}) is True
    assert _valid_transport({"kind": "node", "node_id": "x", "output": "relay1"}) is True
