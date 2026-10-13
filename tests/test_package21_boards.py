"""Package 21: the broker, the parts, the camera and the power.

Read from the sources, like the other firmware checks: each test names what a board
did wrong and fails if the code drifts back to it.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / "firmware" / "brain-core" / "main"
CAM = ROOT / "firmware" / "vision-core"


def _src(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _fn(src: str, sig: str) -> str:
    """Body of the function whose definition starts with `sig`."""
    start = src.index(sig)
    i = src.index("{", start)
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
    raise AssertionError(f"unbalanced braces after {sig}")


# ── D2: «take a photo» from the app was dropped as the camera's own echo ──

def test_the_camera_takes_a_snapshot_command_on_the_topic_it_subscribes_to():
    mqtt = _src(CAM / "cam_mqtt.ino")
    subscribed = re.search(r"kSimpleOutputs\[\] = \{([^}]*)\}", mqtt).group(1)
    assert '"snapshot"' in subscribed
    echo = re.search(r"if \((out == \"status\"[^)]*)\) return;", mqtt).group(1)
    assert '"snapshot"' not in echo, (
        "cam/snapshot is a command the app sends, not something the camera publishes")
    # The camera never publishes on it, so no topic is kept for it.
    assert "g_topicSnapshot" not in mqtt
    assert "TOPIC_SUFFIX_SNAPSHOT" not in _src(CAM / "config.h")
