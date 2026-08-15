# Security

## Reporting a vulnerability

Email **ohnabeel@gmail.com** with `SECURITY` in the subject. Please do not open a
public issue for anything exploitable.

Useful things to include: what you did, what happened, and what you think an
attacker could do with it. A rough description beats no report — the details can
be worked out together.

You will get an acknowledgement within 72 hours.

## What this system holds

Sandy stores personal data: conversations, memories, tasks, reminders, journal
entries, photos, and voiceprints. Any issue that could expose one person's data
to another is treated as the most serious class, ahead of availability.

## Where the boundaries are

- **Tenant isolation** — `cloud/app/utils/tenant_db.py`. Every read and write
  goes through a scoped collection that stamps the caller's tenant onto the query
  and the document. It fails closed: no database or no authenticated tenant means
  no data, not all data. A path that bypasses it is a bug worth reporting even
  without a proof of exploit.
- **Device actuation** — `device_store.tenant_owns_topic`. A tenant can only
  drive hardware registered to their own account.
- **The voice link** — HMAC handshake with a ±30 second replay window. With no
  key configured the socket refuses connections rather than accepting them.
- **Secrets** — `.env`, `secrets.h` and service-account keys are gitignored, and
  CI fails the build if one is ever committed.

## Known and accepted

These are deliberate, documented positions rather than oversights:

- **Usage metering fails open.** A brief database outage lets requests through
  rather than blocking every user. The cost risk is narrow; the availability cost
  of the alternative is not.
- **The room node's fixed `room/cmd/*` topics carry no device identity**, so
  actuation on them is restricted to the owner until that node moves to the
  per-node namespace the robot already uses.

## Not in scope

Findings that need physical access to an unlocked device, or the owner's own
credentials, are not vulnerabilities in this system.
