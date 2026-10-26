"""One check for everything: lint, tests, build, e2e. Last line is CHECK: PASS or FAIL."""

import subprocess
import sys
import time

from _common import BACKEND, FRONTEND, ROOT, tool, venv_python


def main() -> int:
    # A Windows console uses cp1251; tool output can contain other characters.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    py = str(venv_python())
    npm, npx = tool("npm"), tool("npx")
    steps = [
        ("ruff check", [py, "-m", "ruff", "check", "backend", "scripts"], ROOT),
        ("ruff format", [py, "-m", "ruff", "format", "--check", "backend", "scripts"], ROOT),
        ("pytest", [py, "-m", "pytest"], BACKEND),
        ("typecheck", [npm, "run", "typecheck"], FRONTEND),
        ("lint", [npm, "run", "lint"], FRONTEND),
        ("vitest", [npm, "test"], FRONTEND),
        ("build", [npm, "run", "build"], FRONTEND),
        ("e2e", [npx, "playwright", "test"], FRONTEND),
    ]
    failed = []
    for name, cmd, cwd in steps:
        start = time.time()
        p = subprocess.run(
            cmd,
            check=False,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        status = "ok" if p.returncode == 0 else "FAIL"
        print(f"{status:4} {name} ({time.time() - start:.1f}s)", flush=True)
        if p.returncode != 0:
            failed.append(name)
            print((p.stdout + p.stderr).strip(), flush=True)
    print("CHECK: PASS" if not failed else f"CHECK: FAIL ({', '.join(failed)})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
