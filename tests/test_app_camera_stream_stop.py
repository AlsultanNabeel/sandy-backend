"""Leaving the camera screen stops the stream: the board kept serving it (warm, slower
at everything else) until someone came back and pressed stop."""
from pathlib import Path

SRC = (Path(__file__).resolve().parent.parent / "ios" / "SandyApp" / "Features" / "Control"
       / "CameraView.swift").read_text(encoding="utf-8")


def test_leaving_the_screen_stops_the_stream():
    body = SRC[SRC.index("    var body: some View {"):SRC.index("// ── صورة وحدة")]
    assert ".onDisappear" in body and "stopStream()" in body
