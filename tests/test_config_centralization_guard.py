"""Guard: raw environment reads must not grow outside the central config module.

``app.config`` is meant to be the single place the app reads its environment:
named constants, validated once at boot, no defaults duplicated across files.
Some call sites still read ``os.getenv`` directly — integrations that lazily
bind their own API keys, mostly — and retiring those is incremental work. This
test freezes the current count so the number can only go *down*: a new direct
``os.getenv`` / ``os.environ`` read fails the build, nudging it into
``app.config`` instead. When you migrate a call site, lower ``BASELINE`` to match.
"""

import pathlib
import re

APP_DIR = pathlib.Path(__file__).resolve().parents[1] / "cloud" / "app"

# Frozen count of direct env reads outside app/config.py. Only ever ratchet down.
BASELINE = 103

_ENV_READ = re.compile(r"os\.(getenv|environ)")


def _count_direct_env_reads():
    total = 0
    hits = []
    for path in APP_DIR.rglob("*.py"):
        if path.name == "config.py":
            continue
        n = len(_ENV_READ.findall(path.read_text(encoding="utf-8")))
        if n:
            hits.append((str(path.relative_to(APP_DIR)), n))
            total += n
    return total, hits


def test_direct_env_reads_do_not_grow():
    total, hits = _count_direct_env_reads()
    assert total <= BASELINE, (
        f"Direct os.getenv/os.environ reads rose to {total} (baseline {BASELINE}). "
        "Read new configuration through app.config instead of os.getenv. "
        f"Current hotspots: {sorted(hits, key=lambda h: -h[1])[:8]}"
    )
