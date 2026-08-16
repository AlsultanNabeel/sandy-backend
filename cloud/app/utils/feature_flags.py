"""Feature flags — turn a risky change on or off without a deploy.

A flag is an env var on the host, so flipping one is a config change and a
restart rather than a release. That is the whole value: a change that turns out
badly is reverted in a minute by whoever noticed, not by whoever can build.

Flags are for changes big enough to want an escape hatch. A flag that has been
on (or off) for months is not a flag any more — it is dead branching, and it
should be deleted along with the path nobody takes.

Every flag defaults to `False`: a build with no configuration behaves like the
build before the flag existed.

`KNOWN_FLAGS` below is currently empty, and that is the correct state. It used to
list three flags for subsystems this repo does not contain — Anthropic prompt
caching (the SDK is not even a dependency here), DSPy-compiled prompts, and
Telegram feedback buttons — carried over from the older single-owner project.
The docstring also described Sandy as a 3–4 user family app, which contradicts
what this is. Stale entries here are worse than none: they describe a system to
anyone reading, and the description was wrong.
"""

from __future__ import annotations

import os
from typing import Iterable, List

_TRUTHY = frozenset({"1", "true", "yes", "on", "enabled", "y"})
_FALSY = frozenset({"0", "false", "no", "off", "disabled", "n", ""})

# Catalog من الـ flags المعروفة — مفيد للـ tagging والـ /flags command لاحقاً
# Empty on purpose — see the module docstring. Add a name here when you add a
# flag, and take it out when the change it guarded stops being risky.
KNOWN_FLAGS: tuple[str, ...] = ()


def _env_name(flag: str) -> str:
    """Convert short flag name to env var name. 'USE_X' → 'SANDY_USE_X'."""
    flag = flag.upper().strip()
    return flag if flag.startswith("SANDY_") else f"SANDY_{flag}"


def is_enabled(flag: str, default: bool = False) -> bool:
    """يرجع True لو الـ flag مفعّل في Heroku Config Vars.

    يقبل القيم: true/1/yes/on/enabled/y (case-insensitive).
    أي قيمة أخرى → default.

        >>> is_enabled("USE_PROMPT_CACHING")
        False
        >>> # بعد ما نضيف SANDY_USE_PROMPT_CACHING=true على Heroku
        >>> is_enabled("USE_PROMPT_CACHING")
        True
    """
    raw = os.getenv(_env_name(flag), "").strip().lower()
    if raw in _TRUTHY:
        return True
    if raw in _FALSY:
        return False
    return default


def get_active_flags(known: Iterable[str] = KNOWN_FLAGS) -> List[str]:
    """يرجع قائمة الـ flags المفعّلة حالياً — للـ Langfuse tagging."""
    return [f.lower() for f in known if is_enabled(f)]


def get_state() -> dict:
    """Snapshot كامل لكل flag معروف (مفيد للـ logging والـ debugging)."""
    return {f.lower(): is_enabled(f) for f in KNOWN_FLAGS}


# ما في مُيسِّرات جاهزة هون. كان فيها تلاتة — تخزين موجّهات أنثروبيك، ودي إس
# باي، وأزرار تقييم بتيليجرام — لأنظمة المستودع ما بيحتويها، وولا وحدة منهن
# انندهت من أي مكان. دالة اسمها `use_prompt_caching()` بتقول لأي حدا بيقرا إنه
# في تخزين موجّهات هون؛ ما كان في. ضيف مُيسِّر لما تضيف راية فعلية.
