"""The brain lives on its own topic tree, and both ends agree on it.

Two things silently break if only one end is edited: the topic shape, and the
node id derivation, which has to match `node_store.code_to_node_id` character
for character. If they disagree the robot sits on another tree and the symptom
is "the command did nothing" with no error anywhere.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_MQTT = _ROOT / "firmware/brain-core/main/sandy_mqtt.c"


def test_the_brain_publishes_under_its_own_node():
    fw = _MQTT.read_text(encoding="utf-8")
    # Every outgoing topic is built in one place, from the node's own base.
    assert '"%s/%s", s_base, suffix' in fw, (
        "the brain no longer builds its topics from its own node base")


def test_the_brain_takes_only_commands_one_level_under_its_id():
    """It subscribes one level deep, and anything deeper that still arrives is dropped
    before the dispatch, so no "unknown output" warning fires."""
    fw = _MQTT.read_text(encoding="utf-8")
    assert '"%s/+", s_base' in fw
    assert "if (strchr(out, '/')) break;" in fw


def test_the_brain_derives_the_node_id_like_the_server():
    """Lowercase, alphanumerics only, from the pairing code."""
    from app.features.node_store import code_to_node_id

    src = _MQTT.read_text(encoding="utf-8")
    assert re.search(r"c\s*-\s*'A'\s*\+\s*'a'", src), (
        "the brain no longer lowercases the pairing code")
    assert re.search(r"c >= 'a' && c <= 'z'\) \|\| \(c >= '0' && c <= '9'", src), (
        "the brain no longer strips the pairing code to alphanumerics")
    assert code_to_node_id("SANDY-84 21") == "sandy8421"
