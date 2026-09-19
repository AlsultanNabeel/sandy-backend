"""The Arduino boards verify who they talk to, and the published image is the sale build."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_no_board_skips_certificate_checks():
    for p in list((ROOT / "vision-core").glob("*.ino")) + [ROOT / "room-node/room-node.ino"]:
        assert "setInsecure" not in p.read_text(), f"{p.name} trusts any server again"


def test_both_boards_carry_the_same_generated_roots():
    a = (ROOT / "vision-core/sandy_ca_roots.h").read_text()
    b = (ROOT / "room-node/sandy_ca_roots.h").read_text()
    assert a == b and "ISRG Root X1" in a and "DigiCert Global Root G2" in a


def test_only_the_sale_build_is_published():
    src = (ROOT / "scripts/publish_firmware.py").read_text()
    assert '"build-retail"' in src and "logsrv" in src
    cfg = (ROOT / "firmware/brain-core/main/include/config.h").read_text()
    assert "SANDY_RETAIL" in cfg


def test_room_node_understands_every_music_word_the_server_sends():
    from app.integrations.room_device import normalize_action
    src = (ROOT / "room-node/room-node.ino").read_text()
    body = src[src.index("static void handleMusic"):src.index("static const Device DEVICES")]
    for word in ("on", "off", "stop", "pause", "resume", "next", "prev"):
        assert normalize_action("music", word) == word
        assert f'value == "{word}"' in body, f"the room node ignores «{word}»"


def test_room_node_does_not_play_a_self_test_on_every_boot():
    src = (ROOT / "room-node/room-node.ino").read_text()
    assert "#define DF_SELFTEST        0" in src
