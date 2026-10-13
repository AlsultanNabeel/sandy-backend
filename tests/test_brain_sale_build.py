"""The published brain image is the sale build."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_only_the_sale_build_is_published():
    src = (ROOT / "scripts/publish_firmware.py").read_text()
    assert '"build-retail"' in src and "logsrv" in src
    cfg = (ROOT / "firmware/brain-core/main/include/config.h").read_text()
    assert "SANDY_RETAIL" in cfg
