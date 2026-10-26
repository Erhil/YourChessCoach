"""Build the frontend and start the app. Use --no-build to skip the build."""

import os
import signal
import subprocess
import sys

from _common import BACKEND, FRONTEND, ROOT, read_dotenv, ssl_args, tool, venv_python

sys.path.insert(0, str(BACKEND))
from app.config import settings


def main() -> int:
    if "--no-build" not in sys.argv:
        subprocess.run([tool("npm"), "run", "build"], cwd=FRONTEND, check=True)
    host, port = settings.app_host, str(settings.app_port)
    scheme = "https" if ssl_args() else "http"
    print(f"App: {scheme}://{'127.0.0.1' if host == '0.0.0.0' else host}:{port}", flush=True)
    cmd = [
        str(venv_python()),
        "-m",
        "uvicorn",
        "app.main:app",
        "--app-dir",
        str(BACKEND),
        "--host",
        host,
        "--port",
        port,
        *ssl_args(),
    ]
    # Stop uvicorn together with this script: Ctrl+C, SIGTERM and Ctrl+Break all end up in finally.
    for name in ("SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), signal.default_int_handler)
    env = {**read_dotenv(), **os.environ}
    child = subprocess.Popen(cmd, cwd=ROOT, env=env)
    try:
        return child.wait()
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
