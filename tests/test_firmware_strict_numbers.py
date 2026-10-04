"""Broker commands take a whole number or nothing.

atoi turns an empty or garbled value into zero: an empty volume muted her, an
empty angle swung the neck to its end, an empty gain silenced a mic. Every
handler now goes through one strict parser, and this keeps atoi from coming back.
"""
from __future__ import annotations

from pathlib import Path

MQTT = Path(__file__).resolve().parent.parent / "firmware/brain-core/main/sandy_mqtt.c"


def test_no_handler_reads_a_number_with_atoi():
    src = MQTT.read_text(encoding="utf-8")
    code = "\n".join(line for line in src.splitlines() if not line.lstrip().startswith("//"))
    assert "atoi(" not in code


def test_each_numeric_handler_uses_the_strict_parser():
    src = MQTT.read_text(encoding="utf-8")
    for handler in ("_handle_servo", "_handle_mic_gain", "_handle_volume"):
        body = src[src.index(f"static void {handler}("):]
        body = body[:body.index("\n}\n")]
        assert "parse_int(" in body, handler
