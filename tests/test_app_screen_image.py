"""A photo for her screen is sent as a small JPEG made on the phone. Sent as picked, an
iPhone photo is HEIC the server cannot open, and a full-size one is past its 8 MB."""
from pathlib import Path

SRC = (Path(__file__).resolve().parent.parent / "ios" / "SandyApp" / "Features" / "Control"
       / "RobotControlView.swift").read_text(encoding="utf-8")


def test_the_screen_photo_is_made_a_small_jpeg_first():
    upload = SRC[SRC.index("private func upload("):SRC.index("// ── أقسام")]
    assert "ImageDownscale.jpeg(" in upload
    assert "jpegData: data)" not in upload
