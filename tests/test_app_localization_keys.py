"""Every sentence the app asks for exists. A missing key shows the key itself on screen
(«control.camera.noFrames» was the camera's «no picture yet»: the sentence sat in the
robot table under another name)."""
import re
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "ios" / "SandyApp"


def _tables():
    tables = {}
    for f in (APP / "Localization").glob("L10n+*.swift"):
        src = f.read_text(encoding="utf-8")
        ns = re.search(r'static let ns = "([^"]+)"', src)
        if ns:
            tables[ns.group(1)] = set(re.findall(r'^\s*"([^"]+)"\s*:\s*\.(?:text|items)\(', src, re.M))
    return tables


def test_every_key_the_app_asks_for_is_in_its_table():
    tables = _tables()
    assert len(tables) >= 20, "the table pattern stopped matching"
    missing = []
    for f in APP.rglob("*.swift"):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("//"):
                continue
            for ns, key in re.findall(r'\b(?:s|list)\("([a-zA-Z]+)\.([^"\\]+)"\)', line):
                if ns in tables and key not in tables[ns]:
                    missing.append(f"{f.relative_to(APP)}: {ns}.{key}")
    assert not missing, "\n".join(missing)
