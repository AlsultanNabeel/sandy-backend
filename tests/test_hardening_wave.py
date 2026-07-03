"""Regression tests for the security/correctness hardening waves.

Locks in the fixes so they can't silently regress:
- unified Arabic yes/no confirmation matching (the "اه" → hallucinated حذفت bug),
- fetch_url SSRF host filtering,
- per-user pending-state key isolation,
- device transport validation (reserved node namespace).
"""

from app.agent.executor.helpers import _is_quick_confirmation, is_cancellation
from app.agent.executor.pending.dispatch import classify_response_to_pending
from app.agent.tools.schemas.mcp_tools import _is_safe_public_url
from app.agent.pending_store import _key as pending_key
from app.features.device_store import _valid_transport


# ── confirmation matching ────────────────────────────────────────────────────

def test_confirmations_recognized():
    for t in ["اه", "آه", "أه", "اه صح", "اه احذفها", "اه 👍", "تمام", "نعم",
              "ايوه", "احذفها", "ok", "okay", "تمام يلا"]:
        assert _is_quick_confirmation(t), t
        assert classify_response_to_pending(t, "task") == "confirm", t


def test_cancellations_recognized_and_win_mixed():
    for t in ["لا", "لأ", "مش هلأ", "الغي", "خلص", "no", "cancel", "لا تحذف",
              "اه بس لا", "تمام لا مشكلة"]:
        assert is_cancellation(t), t
        assert classify_response_to_pending(t, "task") == "reject", t


def test_non_answers_are_ignored_not_confirmed():
    for t in ["شو الطقس اليوم", "اي واحدة", "احكيلي قصة", ""]:
        assert not _is_quick_confirmation(t), t
        assert classify_response_to_pending(t, "task") == "ignore", t


# ── fetch_url SSRF host filter ───────────────────────────────────────────────

def test_fetch_url_rejects_internal_hosts():
    for u in [
        "http://169.254.169.254/latest/meta-data/",   # cloud metadata
        "http://127.0.0.1/",                           # loopback
        "http://10.0.0.5/",                            # private
        "http://192.168.1.1/",                         # private
        "http://[::1]/",                               # ipv6 loopback
        "ftp://example.com/",                          # non-http scheme
        "not a url",
    ]:
        assert _is_safe_public_url(u) is False, u


def test_fetch_url_allows_public_ip_literal():
    # 8.8.8.8 is a public literal → no DNS, hermetic.
    assert _is_safe_public_url("http://8.8.8.8/") is True


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
