"""Authenticated encryption for database dumps; backup keys never enter artifacts."""

import hashlib
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"AIE-BACKUP-v1\x00"


def encrypt_dump(dump: bytes, key: bytes, destination: Path) -> str:
    if len(key) != 32 or not dump:
        raise ValueError("Nonempty dump and 256-bit external key required")
    if destination.exists():
        raise FileExistsError("Never overwrite an existing backup")
    destination.parent.mkdir(parents=True, exist_ok=True)
    nonce = os.urandom(12)
    encrypted = MAGIC + nonce + AESGCM(key).encrypt(nonce, dump, MAGIC)
    # Exclusive create plus restrictive permissions avoids accidental disclosure/replacement.
    with destination.open("xb") as target:
        os.chmod(destination, 0o600)
        target.write(encrypted)
    return hashlib.sha256(encrypted).hexdigest()


def decrypt_dump(source: Path, key: bytes) -> bytes:
    payload = source.read_bytes()
    if not payload.startswith(MAGIC):
        raise ValueError("Unknown backup format")
    offset = len(MAGIC)
    return AESGCM(key).decrypt(payload[offset : offset + 12], payload[offset + 12 :], MAGIC)
