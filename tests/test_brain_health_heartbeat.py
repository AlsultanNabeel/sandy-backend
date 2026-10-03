"""The brain's heartbeat carries its health, and the server keeps it in shape."""
from __future__ import annotations

from app.features import node_store


def test_health_members_are_kept_and_bounded():
    out = node_store._clean_telemetry({
        "boot": 4, "boots": 17, "heap_min": 9000, "heap_big": 6100, "safe": False,
        "nvs_wiped": True, "nvs_used": 120, "nvs_total": 504,
        "faults": {"net": "no_wifi", "voice": "voice_off"},
        "stacks": {f"task{n}": n for n in range(40)},
        "nonsense": 1,
    })
    assert out["boot"] == 4 and out["boots"] == 17 and out["safe"] is False
    assert out["nvs_wiped"] is True and out["nvs_used"] == 120
    assert out["faults"] == {"net": "no_wifi", "voice": "voice_off"}
    assert len(out["stacks"]) == node_store._DICT_MAX_ITEMS
    assert "nonsense" not in out


def test_a_cleared_fault_list_replaces_the_old_one():
    current = {"telemetry": {"faults": {"net": "no_wifi"}}}
    merged = node_store._merge_telemetry(current, {"faults": {}})
    assert merged["faults"] == {}


def test_a_dict_member_that_is_not_a_dict_is_dropped():
    assert "faults" not in node_store._clean_telemetry({"faults": "net"})
