"""Shared helpers for setup/check/run scripts."""

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
BACKEND = ROOT / "backend"
VENV = ROOT / ".venv"


def read_dotenv() -> dict[str, str]:
    """Variables from the main REPO/.env (the same rules as backend/app/config.py)."""
    values: dict[str, str] = {}
    path = ROOT / ".env"
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("\"'")
    return values


def ssl_args() -> list[str]:
    """uvicorn options for HTTPS, when APP_SSL_CERTFILE and APP_SSL_KEYFILE are both set."""
    env = {**read_dotenv(), **os.environ}
    cert, key = env.get("APP_SSL_CERTFILE", ""), env.get("APP_SSL_KEYFILE", "")
    return ["--ssl-certfile", cert, "--ssl-keyfile", key] if cert and key else []


def venv_python() -> Path:
    sub = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    return VENV / sub


def tool(name: str) -> str:
    """Find an executable (npm.cmd on Windows) or exit."""
    found = shutil.which(name)
    if not found:
        sys.exit(f"'{name}' not found in PATH")
    return found
