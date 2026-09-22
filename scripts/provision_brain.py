#!/usr/bin/env python3
"""Give one robot its identity at production, without putting it in any image.

    python3 scripts/provision_brain.py --pair SANDY-8421 --port /dev/cu.usbmodem1101

Writes the `fctry` partition (firmware/brain-core/partitions.csv) with this
unit's pairing code, broker, voice server and keys, in the namespace the
firmware reads (`sandy_id`, see main/sandy_identity.c). The app image flashed
next to it is the same retail image for every robot — the one the server also
hands out as an update — so nothing private is ever in a published file.

The shared values (broker URI and login, voice URI, voice key) default to the
ones in firmware/brain-core/main/secrets.h, so the everyday call only names the
pairing code. `--out` writes the partition image and skips flashing.

Needs the ESP-IDF Python environment (esp-idf-nvs-partition-gen, esptool) —
run it from an `. $IDF_PATH/export.sh` shell.
"""
from __future__ import annotations

import argparse
import csv
import pathlib
import re
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
FW = REPO / "firmware" / "brain-core"
SECRETS = FW / "main" / "secrets.h"
PARTITIONS = FW / "partitions.csv"
NAMESPACE = "sandy_id"
PAIR_RE = re.compile(r"^[A-Za-z0-9-]{4,23}$")

# key in NVS → (secrets.h name, what it is). Keys are the ones sandy_identity.c reads.
FIELDS = {
    "pair":  ("SANDY_PAIR_CODE",    "pairing code printed on the box"),
    "mqtt":  ("MQTT_BROKER_URI",    "broker URI (mqtts://…:8883)"),
    "mu":    ("MQTT_USER",          "shared broker user (first boot only)"),
    "mp":    ("MQTT_PASS",          "shared broker password (first boot only)"),
    "voice": ("SANDY_VOICE_WS_URI", "voice server (wss://…/voice)"),
    "hmac":  ("SANDY_WS_HMAC_KEY",  "shared voice key (first boot only)"),
}


def _secrets() -> dict:
    if not SECRETS.exists():
        return {}
    return dict(re.findall(r'#define\s+(\w+)\s+"([^"\n]*)"', SECRETS.read_text()))


def _placeholder(v: str) -> bool:
    return not v or "YOUR_" in v or "XXXX" in v


def _partition(name: str) -> tuple[int, int]:
    for row in csv.reader(ln for ln in PARTITIONS.read_text().splitlines()
                          if ln.strip() and not ln.lstrip().startswith("#")):
        cells = [c.strip() for c in row]
        if cells and cells[0] == name:
            return int(cells[3], 16), int(cells[4], 16)
    sys.exit(f"no '{name}' partition in {PARTITIONS} — flash the new table first")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--pair", required=True, help="the pairing code on the box")
    for key, (name, what) in FIELDS.items():
        if key != "pair":
            ap.add_argument(f"--{key}", help=f"{what}; default from secrets.h {name}")
    ap.add_argument("--port", help="serial port to flash")
    ap.add_argument("--out", help="write the partition image here instead of flashing")
    a = ap.parse_args()

    if not PAIR_RE.match(a.pair) or "XXXX" in a.pair:
        sys.exit("the pairing code should look like SANDY-8421")
    known = _secrets()
    values = {"pair": a.pair}
    for key, (name, what) in FIELDS.items():
        if key == "pair":
            continue
        v = getattr(a, key) or known.get(name, "")
        if _placeholder(v):
            sys.exit(f"no {what}: pass --{key} or set {name} in secrets.h")
        values[key] = v

    offset, size = _partition("fctry")
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = pathlib.Path(tmp) / "fctry.csv"
        with csv_path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["key", "type", "encoding", "value"])
            w.writerow([NAMESPACE, "namespace", "", ""])
            for k, v in values.items():
                w.writerow([k, "data", "string", v])
        out = pathlib.Path(a.out) if a.out else pathlib.Path(tmp) / "fctry.bin"
        subprocess.run([sys.executable, "-m", "esp_idf_nvs_partition_gen", "generate",
                        str(csv_path), str(out), hex(size)], check=True)
        if a.out:
            print(f"wrote {out} — flash it at {hex(offset)}")
            return 0
        if not a.port:
            sys.exit("--port is required to flash (or pass --out)")
        subprocess.run([sys.executable, "-m", "esptool", "--chip", "esp32s3", "--port", a.port,
                        "write-flash", hex(offset), str(out)], check=True)
    print(f"{a.pair}: identity written at {hex(offset)}. It is read on the next boot.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
