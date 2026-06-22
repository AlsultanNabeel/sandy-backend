#!/usr/bin/env python
"""Phase 1 migration — copy the owner's data into the clean product DB.

What this does
--------------
Sandy currently runs on the owner's personal shared database (``sany-db``), where
all of his data is tagged with the legacy Telegram id (``SANDY_USER_CHAT_ID`` =
628544372). The product gets its OWN database (default ``sandy-app``) and the owner
becomes tenant #1 under a fresh, clean tenant id.

Decisions baked in (owner-approved 2026-06-22):
  * Fresh clean owner id  — the canonical owner tenant id is the owner's
    ``sandy_users`` account uuid (provider="owner"). If no owner account exists
    yet, one is minted. This unifies the auth identity layer with the data layer:
    after Phase 3, ``/api/auth`` issues this same uuid instead of 628544372.
  * Migrate everything — every collection the owner's data lives in is copied,
    plus any legacy untagged docs (predating per-user isolation), which belong to
    the owner (he was the only user before multi-user landed).

Safety
------
  * Copy-only. The source DB is never modified or deleted — pure read.
  * Idempotent. Re-running upserts the same docs (deterministic ids where the id
    is derived from the tenant; preserved ids otherwise).
  * Dry-run by default. Nothing is written without ``--apply``.

Two id quirks handled (the id encodes the tenant, so it must be rewritten):
  * sandy_facts            : ``_id`` = hash(chat_id : text)  -> recomputed.
  * sandy_focus_meta       : ``_id`` = "sounds:<uid>"        -> substring swap.
  * sandy_voiceprints      : ``_id`` = "<chat_id>"           -> substring swap.

Usage
-----
  ~/sandy_app_venv/bin/python cloud/migrations/001_migrate_owner_to_product_tenant.py            # dry run
  ~/sandy_app_venv/bin/python cloud/migrations/001_migrate_owner_to_product_tenant.py --apply    # write

  Optional: --source-db, --dest-db, --owner-source-id, --owner-dest-id,
            --no-claim-legacy
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

# Make `app.*` importable no matter the working directory.
CLOUD_DIR = Path(__file__).resolve().parents[1]
if str(CLOUD_DIR) not in sys.path:
    sys.path.insert(0, str(CLOUD_DIR))

from app.config import MONGODB_URI, MONGODB_DB_NAME, SANDY_USER_CHAT_ID
from app.integrations.mongodb_store import init_mongo_connection
# Single source of truth for the fact id formula — keep in sync with writes.
from app.agent.semantic_memory import _fact_id

# ── id strategies ──────────────────────────────────────────────────────────
KEEP = "keep"               # _id has no tenant in it; preserve as-is.
SWAP = "swap_in_id"         # _id is a string containing the tenant id; swap it.
REHASH_FACT = "rehash_fact"  # _id = _fact_id(text, tenant); recompute.

# ── collection registry ────────────────────────────────────────────────────
# Each entry: collection name, the tenant field(s) to remap, and how to treat _id.
# Fields verified against the stores in cloud/app. Transient/infra collections
# (sandy_stm, sandy_session_state, sandy_usage_*, sandy_email_seen, sandy_sa_kv,
# sandy_auth, guest_usage) are intentionally excluded — they regenerate or are
# not owner content.
REGISTRY: List[Dict[str, Any]] = [
    # user_id-scoped feature stores
    {"coll": "sandy_tasks",            "fields": ["user_id"], "id": KEEP},
    {"coll": "sandy_habits",           "fields": ["user_id"], "id": KEEP},
    {"coll": "sandy_habit_log",        "fields": ["user_id"], "id": KEEP},
    {"coll": "sandy_reminders",        "fields": ["user_id"], "id": KEEP},
    {"coll": "sandy_expenses",         "fields": ["user_id"], "id": KEEP},
    {"coll": "sandy_scenes",           "fields": ["user_id"], "id": KEEP},
    {"coll": "sandy_focus",            "fields": ["user_id"], "id": KEEP},
    {"coll": "sandy_focus_meta",       "fields": ["user_id"], "id": SWAP},
    {"coll": "sandy_shopping",         "fields": ["user_id"], "id": KEEP},
    {"coll": "sandy_books",            "fields": ["user_id"], "id": KEEP},
    {"coll": "sandy_reading_sessions", "fields": ["user_id"], "id": KEEP},
    {"coll": "sandy_reading_meta",     "fields": ["user_id"], "id": KEEP},
    {"coll": "sandy_journal",          "fields": ["user_id"], "id": KEEP},
    # chat_id-scoped memory / brain
    {"coll": "sandy_facts",            "fields": ["chat_id"], "id": REHASH_FACT},
    {"coll": "sandy_conversations",    "fields": ["chat_id"], "id": KEEP},
    {"coll": "sandy_context_metadata", "fields": ["chat_id"], "id": KEEP},
    {"coll": "sandy_memories",         "fields": ["chat_id", "user_id"], "id": KEEP},
    {"coll": "sandy_goals",            "fields": ["chat_id", "user_id"], "id": KEEP},
    {"coll": "sandy_brainstorms",      "fields": ["chat_id"], "id": KEEP},
    {"coll": "sandy_voiceprints",      "fields": ["chat_id"], "id": SWAP},
    {"coll": "sandy_photo_files",      "fields": ["chat_id"], "id": KEEP},
    {"coll": "sandy_future_messages",  "fields": ["chat_id", "user_id"], "id": KEEP},
    {"coll": "sandy_activity",         "fields": ["chat_id", "user_id"], "id": KEEP},
]


def _is_legacy(value: Any) -> bool:
    """True for docs that predate per-user isolation (no tenant on the field)."""
    return value is None or value == ""


def _build_filter(fields: List[str], source_id: str, claim_legacy: bool) -> Dict[str, Any]:
    clauses: List[Dict[str, Any]] = [{f: source_id} for f in fields]
    if claim_legacy:
        primary = fields[0]
        clauses.append({primary: {"$exists": False}})
        clauses.append({primary: None})
    return {"$or": clauses}


def _remap_fields(doc: Dict[str, Any], fields: List[str], source_id: str, dest_id: str) -> None:
    """Set every tenant field that points at the owner (or is legacy) to dest_id."""
    primary = fields[0]
    matched_primary = False
    for f in fields:
        cur = doc.get(f)
        if str(cur) == source_id or _is_legacy(cur):
            doc[f] = dest_id
            if f == primary:
                matched_primary = True
    # Legacy doc that was missing the primary field entirely.
    if not matched_primary:
        doc[primary] = dest_id


def _new_id(doc: Dict[str, Any], strategy: str, source_id: str, dest_id: str) -> Any:
    old = doc.get("_id")
    if strategy == SWAP:
        return str(old).replace(source_id, dest_id)
    if strategy == REHASH_FACT:
        return _fact_id((doc.get("text") or "").strip(), dest_id)
    return old


def _resolve_owner_dest_id(
    dest_db: Any, source_db: Any, override: Optional[str]
) -> str:
    if override:
        return override
    for db in (dest_db, source_db):
        existing = db["sandy_users"].find_one({"provider": "owner"})
        if existing and existing.get("_id"):
            return str(existing["_id"])
    return uuid.uuid4().hex


def _ensure_owner_account(
    dest_db: Any, source_db: Any, owner_dest_id: str, source_id: str, apply: bool
) -> None:
    """Make sure the owner has a sandy_users account (carrying onboarding) in dest."""
    src = source_db["sandy_users"].find_one({"provider": "owner"}) or {}
    doc = dict(src)
    doc["_id"] = owner_dest_id
    doc.setdefault("provider", "owner")
    doc.setdefault("provider_sub", source_id)
    doc.setdefault(
        "onboarding",
        {"done": False, "preferred_name": "", "interests": [], "notes": ""},
    )
    doc.setdefault(
        "subscription",
        {"status": "active", "plan": "owner", "trial_ends_at": None,
         "current_period_end": None, "source": "owner"},
    )
    if apply:
        dest_db["sandy_users"].replace_one({"_id": owner_dest_id}, doc, upsert=True)


def migrate(
    source_db: Any,
    dest_db: Any,
    source_id: str,
    dest_id: str,
    claim_legacy: bool,
    apply: bool,
) -> None:
    print(f"\n  owner source id : {source_id}")
    print(f"  owner dest id   : {dest_id}")
    print(f"  claim legacy    : {claim_legacy}")
    print(f"  mode            : {'APPLY (writing)' if apply else 'DRY RUN (no writes)'}\n")

    _ensure_owner_account(dest_db, source_db, dest_id, source_id, apply)

    total = 0
    for entry in REGISTRY:
        coll, fields, strategy = entry["coll"], entry["fields"], entry["id"]
        filt = _build_filter(fields, source_id, claim_legacy)
        copied = 0
        for doc in source_db[coll].find(filt):
            doc = dict(doc)
            _remap_fields(doc, fields, source_id, dest_id)
            doc["_id"] = _new_id(doc, strategy, source_id, dest_id)
            if apply:
                dest_db[coll].replace_one({"_id": doc["_id"]}, doc, upsert=True)
            copied += 1
        total += copied
        print(f"  {coll:<26} {copied:>6} doc(s)")

    print(f"\n  total: {total} doc(s) {'copied' if apply else 'would be copied'}")
    if not apply:
        print("  (dry run — re-run with --apply to write)")
    print(f"\n  >> owner tenant id = {dest_id}")
    print("     wire this into /api/auth in Phase 3 (de-owner).\n")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true", help="write to dest (default: dry run)")
    p.add_argument("--source-db", default=MONGODB_DB_NAME, help="legacy DB (default: %(default)s)")
    p.add_argument("--dest-db", default="sandy-app", help="product DB (default: %(default)s)")
    p.add_argument("--owner-source-id", default=str(SANDY_USER_CHAT_ID).strip(),
                   help="legacy owner tenant id (default: SANDY_USER_CHAT_ID)")
    p.add_argument("--owner-dest-id", default=None,
                   help="override the clean owner id (default: owner's sandy_users uuid)")
    p.add_argument("--no-claim-legacy", action="store_true",
                   help="do NOT migrate legacy untagged docs")
    args = p.parse_args()

    if not MONGODB_URI:
        print("ERROR: MONGODB_URI is not set.", file=sys.stderr)
        return 2
    if not args.owner_source_id:
        print("ERROR: owner source id is empty (set SANDY_USER_CHAT_ID or pass "
              "--owner-source-id).", file=sys.stderr)
        return 2
    if args.source_db == args.dest_db:
        print(f"ERROR: source and dest DB are both '{args.source_db}'. Refusing.",
              file=sys.stderr)
        return 2

    _, source_db = init_mongo_connection(MONGODB_URI, args.source_db)
    _, dest_db = init_mongo_connection(MONGODB_URI, args.dest_db)
    if source_db is None or dest_db is None:
        print("ERROR: could not connect to MongoDB.", file=sys.stderr)
        return 2

    dest_id = _resolve_owner_dest_id(dest_db, source_db, args.owner_dest_id)
    print(f"\n=== Phase 1 owner migration: {args.source_db} -> {args.dest_db} ===")
    migrate(
        source_db=source_db,
        dest_db=dest_db,
        source_id=args.owner_source_id,
        dest_id=dest_id,
        claim_legacy=not args.no_claim_legacy,
        apply=args.apply,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
