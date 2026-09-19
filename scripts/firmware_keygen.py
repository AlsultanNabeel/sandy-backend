#!/usr/bin/env python3
"""Create the firmware signing key pair — once, ever.

The PRIVATE key signs every release and must never enter the repository or the
server: whoever holds it can install anything on every robot. Keep a backup
somewhere safe (a password manager, an encrypted USB stick). Losing it means no
robot in the field can be updated without a cable.

The PUBLIC key is compiled into the firmware (main/fw_pubkey.pem) and is what a
robot checks every release against.

    python3 scripts/firmware_keygen.py ~/Desktop/.sandy-signing/firmware-signing-key.pem
"""

import os
import pathlib
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

REPO = pathlib.Path(__file__).resolve().parents[1]
PUBLIC = REPO / "firmware" / "brain-core" / "main" / "fw_pubkey.pem"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    private = pathlib.Path(sys.argv[1]).expanduser()
    if private.exists():
        print(f"refusing: {private} already exists — a second key would orphan every "
              "robot that trusts the first")
        return 1
    private.parent.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    fd = os.open(private, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM,
                                  serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()))
    PUBLIC.write_bytes(key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    print(f"private key: {private}  (back it up; never commit it)")
    print(f"public key:  {PUBLIC}  (commit this; it is built into the firmware)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
