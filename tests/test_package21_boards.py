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


# ── D6: the app offered picture sizes the camera clips without a word ──

def test_the_app_offers_no_picture_size_past_the_cameras_largest():
    from app.features.node_provision import PART_CATALOGUE

    control = _src(CAM / "cam_control.ino")
    order = re.findall(r'\{"([\w\d]+)",\s*FRAMESIZE_(\w+)\}', control)
    assert len(order) >= 10, "the camera's size table stopped matching"
    config = _src(CAM / "config.h")
    largest = re.search(r"#define CAMERA_MAX_FRAME_SIZE\s+(\w+)", config).group(1)
    if largest == "CAMERA_DEFAULT_FRAME_SIZE":
        largest = re.search(r"#define CAMERA_DEFAULT_FRAME_SIZE\s+FRAMESIZE_(\w+)",
                            config).group(1)
    names = [name for name, _ in order]
    cap = [size for _, size in order].index(largest.removeprefix("FRAMESIZE_"))
    allowed = set(names[:cap + 1])

    offered = list(PART_CATALOGUE["cam/framesize"]["meta"]["values"])
    assert set(offered) <= allowed, (
        f"{sorted(set(offered) - allowed)} are past the camera's largest ({largest}): "
        "it clips them and the server records a size the photo never had")
    assert offered == names[:cap + 1], "every size up to the largest, smallest first"
