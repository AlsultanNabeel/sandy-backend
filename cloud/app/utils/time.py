"""The user's clock: each user's own time zone, sent by their phone.

`USER_TZ` is one tzinfo that answers for whoever the active tenant is: the zone their
phone last sent (`X-Timezone` on any signed-in request, kept on `sandy_users.timezone`),
else `USER_TIMEZONE`. So every «today», «at five» and «this week» is read on the
user's own clock, in requests and in the background runners alike, which run inside
the tenant's context.
"""

import logging
import os
import threading
import time
from datetime import datetime, timedelta, tzinfo
from typing import Dict, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

DEFAULT_ZONE = os.getenv("USER_TIMEZONE", "Africa/Cairo")
_DEFAULT = ZoneInfo(DEFAULT_ZONE)
# How long a user's zone is trusted before it is read again (another worker may have changed it,
# and the schedule runner on this one rings repeats by it).
_TTL_SECONDS = 60
_cache: Dict[str, Tuple[ZoneInfo, float]] = {}
_lock = threading.Lock()


def _zone_or_none(name: str) -> Optional[ZoneInfo]:
    try:
        return ZoneInfo(str(name or "").strip()) if name else None
    except (ZoneInfoNotFoundError, ValueError):
        return None


def zone_for(user_id: Optional[str]) -> ZoneInfo:
    """The user's zone, cached; the default with no user or none known."""
    if not user_id:
        return _DEFAULT
    hit = _cache.get(user_id)
    if hit and hit[1] > time.monotonic():
        return hit[0]
    from app.features import users_store

    zone = _zone_or_none((users_store.get_user(user_id) or {}).get("timezone")) or _DEFAULT
    with _lock:
        _cache[user_id] = (zone, time.monotonic() + _TTL_SECONDS)
    return zone


def note_zone(user_id: Optional[str], name: Optional[str]) -> None:
    """Keep the zone the phone sent when it changed (travel, a new phone); the user's
    repeating reminders move onto the new clock."""
    zone = _zone_or_none(name or "")
    if not user_id or zone is None:
        return
    old = zone_for(user_id)
    if old.key == zone.key:
        return
    from app.features import users_store

    if users_store.set_timezone(user_id, zone.key):
        with _lock:
            _cache[user_id] = (zone, time.monotonic() + _TTL_SECONDS)
        from app.services import schedule_runner

        schedule_runner.follow_zone(user_id, old)


def current_zone() -> ZoneInfo:
    from app.utils.user_profiles import current_user_id

    return zone_for(current_user_id())


def zone_name() -> str:
    return current_zone().key


class _UserZone(tzinfo):
    """Answers with the active tenant's zone at the moment it is asked."""

    def utcoffset(self, dt: Optional[datetime]) -> Optional[timedelta]:
        return current_zone().utcoffset(dt)

    def dst(self, dt: Optional[datetime]) -> Optional[timedelta]:
        return current_zone().dst(dt)

    def tzname(self, dt: Optional[datetime]) -> Optional[str]:
        return current_zone().tzname(dt)

    def fromutc(self, dt: datetime) -> datetime:
        zone = current_zone()
        return zone.fromutc(dt.replace(tzinfo=zone)).replace(tzinfo=self)

    def __repr__(self) -> str:
        return "USER_TZ"


USER_TZ = _UserZone()
