"""The boot guard: a staging server never touches production, and production never runs
on a staging database.

Every database carries the environment that first booted on it (`sandy_env`, one row
`{_id: "env", env: "prod" | "staging"}`), written once when missing. `APP_ENV=staging` is
staging; anything else (prod, dev) is the production side, since a local run works on the
production database.

A staging server is refused when it is wired to production in any way:

- the database is the production one by name (`PROD_DB_NAME`) or by its mark;
- the broker is production's own login (`PROD_BROKER`: host and user together), or the
  production host is in the boards' logins (`SANDY_BROKER_CREDS`);
- a setting only production may hold is set (`STAGING_FORBIDDEN`: pushes, the store's
  webhook, firmware publishing).

Production is refused on a database marked staging. Every problem is named at once, by
setting name only: no value is logged or raised, and no password is read for itself.
`check_settings` runs first in `bootstrap.init_runtime`, before any connection; `check`
runs once the database is open and before anything else touches it or the broker opens.
A refusal stops the boot.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, List, Mapping, Optional

logger = logging.getLogger(__name__)

MARKER = "sandy_env"
PROD_DB_NAME = "sandy-app"
PROD_BROKER = ("aea5cd5ef716450d99e8f06cf1eaba01.s1.eu.hivemq.cloud", "sandy-server")
STAGING_FORBIDDEN_PREFIXES = ("APNS_",)
STAGING_FORBIDDEN = ("REVENUECAT_WEBHOOK_AUTH", "SANDY_FIRMWARE_TOKEN")


class EnvGuardError(RuntimeError):
    """The server is wired to the other environment; it must not start."""


def env_of(environ: Mapping[str, str]) -> str:
    return "staging" if str(environ.get("APP_ENV", "")).strip().lower() == "staging" else "prod"


def _set(environ: Mapping[str, str], name: str) -> bool:
    return bool(str(environ.get(name, "") or "").strip())


def problems(environ: Mapping[str, str]) -> List[str]:
    """What in the settings wires this server to the other environment (names only)."""
    if env_of(environ) != "staging":
        return []
    found: List[str] = []
    if str(environ.get("MONGODB_DB_NAME", "")).strip() == PROD_DB_NAME:
        found.append(f"MONGODB_DB_NAME is the production database ({PROD_DB_NAME})")
    host, user = PROD_BROKER
    if (str(environ.get("SANDY_MQTT_HOST", "")).strip().lower() == host
            and str(environ.get("SANDY_MQTT_USER", "")).strip() == user):
        found.append("SANDY_MQTT_HOST and SANDY_MQTT_USER are the production broker's login")
    if host in str(environ.get("SANDY_BROKER_CREDS", "")).lower():
        found.append("SANDY_BROKER_CREDS points boards at the production broker")
    for name in sorted(environ):
        if (name.startswith(STAGING_FORBIDDEN_PREFIXES) or name in STAGING_FORBIDDEN) \
                and _set(environ, name):
            found.append(f"{name} is set; staging must not have it")
    return found


def _refuse(env: str, found: List[str]) -> None:
    for p in found:
        logger.error("[env_guard] %s", p)
    raise EnvGuardError(f"Sandy ({env}) refuses to start: " + "; ".join(found))


def check_settings(environ: Optional[Mapping[str, str]] = None) -> None:
    """Raise `EnvGuardError` when the settings alone wire this server to the other side."""
    environ = os.environ if environ is None else environ
    found = problems(environ)
    if found:
        _refuse(env_of(environ), found)


def _marked(db: Any) -> Optional[str]:
    row = db[MARKER].find_one({"_id": "env"})
    return str(row.get("env")) if row else None


def check(db: Any, environ: Optional[Mapping[str, str]] = None) -> None:
    """Raise `EnvGuardError` naming every problem; mark the database when it has no mark."""
    environ = os.environ if environ is None else environ
    env = env_of(environ)
    found = problems(environ)
    marked = _marked(db) if db is not None else None
    if marked is not None and marked != env:
        found.append(f"the database is marked {marked}; this server is {env}")
    if found:
        _refuse(env, found)
    if db is not None and marked is None:
        db[MARKER].update_one({"_id": "env"},
                              {"$setOnInsert": {"env": env, "at": datetime.now(timezone.utc)}},
                              upsert=True)
        logger.info("[env_guard] database marked %s", env)
