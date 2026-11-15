"""Run required checks with exit-status preservation, including PostgreSQL if requested."""

import os
import subprocess
import sys
from pathlib import Path

from investment_engine.settings import settings

root = Path(__file__).resolve().parents[1]
os.chdir(root)
environment = {**os.environ, "UV_CACHE_DIR": str(root.parent / ".cache" / "uv")}
if "--postgres" in sys.argv:
    url = settings().database_url.get_secret_value()
    if not url.startswith("postgresql"):
        raise RuntimeError("PostgreSQL settings required")
    environment["TEST_DATABASE_URL"] = url
for command in (
    ["ruff", "check", "src", "tests", "scripts", "streamlit_app.py"],
    ["ruff", "format", "--check", "src", "tests", "scripts", "streamlit_app.py"],
    ["mypy", "src"],
    ["pytest", "-q"],
):
    subprocess.run(["uv", "run", "--frozen", *command], env=environment, check=True)
