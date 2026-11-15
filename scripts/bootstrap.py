"""Local cloud setup. Never overwrites configuration or connects to a live broker."""

import os
import secrets
import subprocess
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    cache = str(root.parent / ".cache" / "uv")
    run_env = {**os.environ, "UV_CACHE_DIR": cache}
    subprocess.run(["uv", "sync", "--frozen"], env=run_env, check=True)
    config = root / ".env"
    if not config.exists():
        password = secrets.token_hex(24)
        with config.open("x") as target:
            os.chmod(config, 0o600)
            target.write(
                "DATABASE_URL=postgresql+psycopg://invest:"
                + password
                + "@127.0.0.1:5432/invest\nPOSTGRES_PASSWORD="
                + password
                + "\nINVEST_EMERGENCY_STOP=true\nINVEST_MARKET_DATA_PERMITTED=false\n"
            )
    else:
        from dotenv import dotenv_values

        password = dotenv_values(config).get("POSTGRES_PASSWORD")
        if not password:
            raise RuntimeError("Existing .env preserved; local PostgreSQL password binding missing")
    subprocess.run(
        ["docker", "compose", "up", "-d", "--wait"],
        env={**run_env, "POSTGRES_PASSWORD": password},
        check=True,
    )
    for args in (["alembic", "upgrade", "head"], ["invest", "doctor"], ["invest", "init"]):
        subprocess.run(["uv", "run", "--frozen", *args], env=run_env, check=True)


if __name__ == "__main__":
    main()
