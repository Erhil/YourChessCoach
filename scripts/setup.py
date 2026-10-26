"""Create .venv, install dependencies, build the frontend, fetch data. Safe to run again.

Usage: python scripts/setup.py [--dev] [--skip-data]
  --dev        also install requirements-dev.txt and the Playwright browsers (chromium, webkit)
  --skip-data  do not download engines, puzzles and openings
"""

import secrets
import subprocess
import sys
import time

from _common import FRONTEND, ROOT, VENV, read_dotenv, tool, venv_python

DATA_SCRIPTS = [
    "download_engines.py",
    "download_puzzles.py",
    "import_puzzles.py",
    "download_openings.py",
]


def run(cmd: list[str], cwd=ROOT) -> None:
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def ensure_admin_token() -> None:
    """Add ADMIN_TOKEN to .env when it is missing. The token itself is never printed."""
    env_file = ROOT / ".env"
    if read_dotenv().get("ADMIN_TOKEN"):
        return
    text = env_file.read_text(encoding="utf-8") if env_file.is_file() else ""
    if text and not text.endswith("\n"):
        text += "\n"
    text += f"# Admin token (page /admin); created by setup.py\nADMIN_TOKEN={secrets.token_urlsafe(24)}\n"
    env_file.write_text(text, encoding="utf-8", newline="\n")
    print(f"ADMIN_TOKEN created in {env_file}")


def main() -> None:
    if sys.version_info < (3, 11):  # noqa: UP036 - this script can run under an older Python
        sys.exit(f"SETUP: FAIL (Python 3.11+ is necessary, this is {sys.version.split()[0]})")
    ensure_admin_token()  # first: /admin must open also when a later step fails
    skip_data = "--skip-data" in sys.argv
    dev = "--dev" in sys.argv
    py = venv_python()
    if not py.exists():
        run([sys.executable, "-m", "venv", str(VENV)])
    requirements = ROOT / ("requirements-dev.txt" if dev else "requirements.txt")
    run([str(py), "-m", "pip", "install", "-q", "-r", str(requirements)])
    installed = FRONTEND / "node_modules" / ".package-lock.json"
    lock = FRONTEND / "package-lock.json"
    if not installed.exists() or installed.stat().st_mtime < lock.stat().st_mtime:
        run([tool("npm"), "ci", "--no-audit", "--no-fund"], cwd=FRONTEND)
    if dev:
        run([tool("npx"), "playwright", "install", "chromium", "webkit"], cwd=FRONTEND)
    run([tool("npm"), "run", "build"], cwd=FRONTEND)  # run.py --no-build and the service need dist
    if not skip_data:
        for name in DATA_SCRIPTS:
            script = ROOT / "scripts" / name
            if script.exists():
                run([str(py), str(script)])
        (VENV / ".setup-done").write_text("", encoding="utf-8")  # run.sh / run.ps1 skip setup
    print("SETUP: done")


if __name__ == "__main__":
    start = time.time()
    try:
        main()
    except subprocess.CalledProcessError as e:
        sys.exit(f"SETUP: FAIL ({e.cmd[:3]} exit {e.returncode})")
    print(f"time: {time.time() - start:.0f}s")
