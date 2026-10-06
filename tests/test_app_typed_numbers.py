"""A number typed on an Arabic keyboard («٥٠») is a number. Swift's `Int(…)` and
`Double(…)` return nil for it, so a field that parsed with them silently fell back (a
budget of 0, a 25-minute focus whatever was typed). Every screen with a number field
reads it through the shared `Digits`."""
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent / "ios" / "SandyApp"

SCREENS = [
    "Features/Life/LifeView.swift",
    "Features/Focus/FocusView.swift",
    "Features/Blocks/BlockEditors.swift",
    "Features/Control/DeviceSheet.swift",
    "Features/Control/NodeSheets.swift",
]


@pytest.mark.parametrize("screen", SCREENS)
def test_a_number_field_reads_arabic_digits(screen):
    src = (APP / screen).read_text(encoding="utf-8")
    assert ".keyboardType(.numberPad)" in src or ".keyboardType(.decimalPad)" in src
    assert "Digits." in src, f"{screen} parses a typed number without Digits"
    for raw in ("Int(focusMin)", "Int(breakMin)", "Int(cycles)",
                'Double(budget.replacingOccurrences', "Int(dimmerMin", "Int(dimmerMax",
                "presence.filter(\\.isNumber)", "v.filter(\\.isNumber)"):
        assert raw not in src, f"{screen} still parses {raw}"
