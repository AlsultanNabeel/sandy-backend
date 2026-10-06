"""A one-shot command is a button, not a remembered choice: a picker only sends when its
value changes, so «take a photo» (its only value) never fired from the card, and the same
melody or gesture twice in a row was the second time nothing. The catalogue marks them
(`meta.momentary`: the values that are one-shot) and the app draws those as buttons."""
from app.features.node_provision import PART_CATALOGUE

ONE_SHOT = {
    "sandy_buzzer": None, "sandy_speaker_test": None, "sandy_gesture": None,
    "cam_snapshot": None, "room_music": ["next", "prev"],
}


def _part(name):
    return next(p for p in PART_CATALOGUE.values() if p["name"] == name)


def test_the_one_shot_parts_are_marked():
    for name, values in ONE_SHOT.items():
        meta = _part(name)["meta"]
        expected = values if values is not None else meta["values"]
        assert meta.get("momentary") == expected, name


def test_the_rest_keep_their_picker():
    for part in PART_CATALOGUE.values():
        if part["name"] not in ONE_SHOT:
            assert "momentary" not in (part.get("meta") or {}), part["name"]
