"""Regressions for batch five: the project following its own rules.

`CONVENTIONS.md` C3 — fire-and-forget goes through `submit_background`, raw
`threading.Thread` is not allowed. Five sites used one, all per request, and a
raw thread does not carry the tenant.
"""
from __future__ import annotations

import ast
import pathlib


ROOT = pathlib.Path(__file__).resolve().parent.parent
CLOUD = ROOT / "cloud" / "app"

# ── C3: no raw threads for fire-and-forget ───────────────────────────────────

def test_fire_and_forget_work_uses_the_shared_pool():
    """Three shapes are exempt and each says so where it sits — a long-lived
    singleton, and work the request itself waits on (`CONVENTIONS.md` C3b).
    Everything else creates a thread per request, unbounded under load, and
    does it without carrying the tenant."""
    exempt = {
        "features/speaker_id.py",       # one-shot model warm-up
        "integrations/mqtt_ingest.py",  # the reconnect watchdog
        "api/server.py",                # /api/agent/stream — the request waits
    }
    offenders = []
    for path in sorted(CLOUD.rglob("*.py")):
        rel = str(path.relative_to(CLOUD))
        if rel in exempt:
            continue
        for node in ast.walk(ast.parse(path.read_text(), rel)):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "Thread"):
                offenders.append(f"{rel}:{node.lineno}")

    assert not offenders, f"raw threads against C3: {offenders}"


def test_the_map_does_not_contradict_itself_about_the_camera():
    """§5 said in bold that `firmware/vision-core/` does not exist while §4.6 said it was
    flashed and answering on the broker. A map that lies is worse than no map."""
    mp = (ROOT / "ARCHITECTURE_MAP.md").read_text()
    assert (ROOT / "firmware" / "vision-core").exists()
    assert "**this directory does not exist.**" not in mp
