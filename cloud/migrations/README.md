# Migrations

One-off data scripts for the product migration (see `PRODUCT_MIGRATION_PLAN.md`).
They are run by hand against MongoDB, never on app boot.

## 001 — owner to product tenant (Phase 1)

Copies the owner's data out of the legacy shared DB (`sany-db`) into the clean
product DB (`sandy-app`) under a fresh canonical owner tenant id (the owner's
`sandy_users` account uuid). Copy-only (source untouched), idempotent, dry-run by
default.

```bash
# preview (no writes):
~/sandy_app_venv/bin/python cloud/migrations/001_migrate_owner_to_product_tenant.py

# perform the copy:
~/sandy_app_venv/bin/python cloud/migrations/001_migrate_owner_to_product_tenant.py --apply
```

The run prints the chosen **owner tenant id** — wire that into `/api/auth` in
Phase 3 (de-owner) so the owner's token carries the new id instead of the legacy
Telegram id. After cut-over, point the app at the new DB with
`MONGODB_DB_NAME=sandy-app`.

Collections covered are listed in `REGISTRY` inside the script. Transient/infra
collections (short-term memory, sessions, usage counters, dedup) are intentionally
skipped.
