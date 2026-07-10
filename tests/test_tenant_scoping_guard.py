"""Guard: the tenant-scoped data tier must not silently regrow a raw second tier.

Per-tenant user data goes through ``app.utils.tenant_db.scoped`` (see
``test_tenant_isolation.py``, which runs every such store through the isolation
contract). A handful of feature stores legitimately touch a *raw* collection —
they are infrastructure or keyed on something other than the tenant id — and
each is listed below with the reason it is allowed.

This test fails when a NEW feature store starts using a raw ``get_db()[...]``
collection. That is the moment to decide: either route the data through
``scoped()`` (if it is per-tenant user data — the common case), or add the file
here with a one-line justification (if it is genuinely infra). Either way the
choice becomes explicit and reviewed, instead of a forgotten filter leaking one
tenant's rows into another's — the class of bug this guard exists to prevent.
"""

import pathlib
import re

FEATURES_DIR = pathlib.Path(__file__).resolve().parents[1] / "cloud" / "app" / "features"

# file -> why it is allowed to touch a raw (non-scoped) collection
ALLOWED_RAW = {
    "push_tokens_store.py": "infra: cross-tenant scheduler fan-out, keyed by device token",
    "usage_store.py": "rate-limit/metering, keyed by composite _id '<user_id>:<date>'",
    "users_store.py": "the identity/tenant table itself — it manages tenants",
    "speaker_id.py": "owner voiceprint, keyed by _id=str(chat_id)",
    "brainstorm.py": "chat-scoped drafts, keyed by chat_id",
    "node_store.py": "physical room nodes, keyed by node_id (device infra)",
    "photo_album.py": "album meta keyed by chat_id/photo_id alongside GridFS",
}

_RAW_ACCESS = re.compile(r"get_db\(\)\[")


def _files_with_raw_access():
    found = set()
    for path in FEATURES_DIR.glob("*.py"):
        if _RAW_ACCESS.search(path.read_text(encoding="utf-8")):
            found.add(path.name)
    return found


def test_no_new_raw_tenant_data_store():
    found = _files_with_raw_access()
    unexpected = found - set(ALLOWED_RAW)
    assert not unexpected, (
        "New raw (non-scoped) collection access in feature store(s): "
        f"{sorted(unexpected)}. Route per-tenant data through app.utils.tenant_db."
        "scoped(); if this is genuinely infra, add it to ALLOWED_RAW with a reason."
    )


def test_allowlist_has_no_stale_entries():
    """Keeps the allowlist honest: an entry that no longer uses raw access should
    be removed so the list keeps meaning something."""
    found = _files_with_raw_access()
    stale = set(ALLOWED_RAW) - found
    assert not stale, f"ALLOWED_RAW lists files that no longer use raw access: {sorted(stale)}"
