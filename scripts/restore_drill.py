"""Verify an encrypted local PostgreSQL backup in a new isolated Docker database.

This only targets the known local Compose container. It never drops/restores the source DB.
The independently stored key is in ignored var/ for this LOCAL drill only; production must
use a managed secret store and an independently recoverable key.
"""

import json
import os
import secrets
import subprocess
from pathlib import Path

from investment_engine.backup import decrypt_dump, encrypt_dump

root = Path(__file__).resolve().parents[1]
os.chdir(root)
backup_dir = root / "var" / "backups"
backup_dir.mkdir(parents=True, exist_ok=True)
key_file = root / "var" / "local-backup-key"
if not key_file.exists():
    with key_file.open("xb") as output:
        os.chmod(key_file, 0o600)
        output.write(os.urandom(32))
key = key_file.read_bytes()
container = subprocess.check_output(
    ["docker", "compose", "ps", "-q", "postgres"], text=True
).strip()
if not container:
    raise RuntimeError("Local PostgreSQL is not running")


def docker(*args: str, data: bytes | None = None) -> bytes:
    return subprocess.run(
        ["docker", "exec", "-i", container, *args], input=data, check=True, stdout=subprocess.PIPE
    ).stdout


dump = docker("pg_dump", "-U", "invest", "-d", "invest", "-Fc", "--no-owner", "--no-acl")
backup = backup_dir / ("postgres-" + secrets.token_hex(8) + ".aie")
checksum = encrypt_dump(dump, key, backup)
restored = decrypt_dump(backup, key)
if restored != dump:
    raise RuntimeError("Encrypted roundtrip mismatch")
target = "restore_drill_" + secrets.token_hex(6)
docker("createdb", "-U", "invest", target)
try:
    docker(
        "pg_restore", "-U", "invest", "-d", target, "--exit-on-error", "--no-owner", data=restored
    )
    # Canonical relation counts verify both data and migration state were restored.
    query = (
        "SELECT 'accounts', count(*)::text FROM accounts UNION ALL "
        "SELECT 'ledger', count(*)::text FROM ledger UNION ALL "
        "SELECT 'orders', count(*)::text FROM orders UNION ALL "
        "SELECT 'bars', count(*)::text FROM bars UNION ALL "
        "SELECT 'schema', version_num FROM alembic_version ORDER BY 1;"
    )
    source = docker("psql", "-U", "invest", "-d", "invest", "-At", "-c", query)
    copy = docker("psql", "-U", "invest", "-d", target, "-At", "-c", query)
    if source != copy:
        raise RuntimeError("Restored relation counts/schema mismatch")
    print(
        json.dumps(
            {
                "status": "restored_and_verified",
                "sha256": checksum,
                "backup": str(backup.relative_to(root)),
                "scope": "local-only; not uploaded to Google Drive",
            }
        )
    )
finally:
    docker("dropdb", "-U", "invest", target)
