"""Create, check, or restore a consistent SQLite snapshot. Never replace a target."""

import argparse
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

if __name__ == "__main__":
    from _common import use_project_python

    use_project_python()

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.db import verified_copy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create", "check", "restore"))
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path, nargs="?")
    args = parser.parse_args()
    try:
        if args.action == "check":
            with closing(
                sqlite3.connect(args.source.resolve().as_uri() + "?mode=ro", uri=True)
            ) as db:
                if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise ValueError("Database integrity check failed")
                counts = {}
                for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                    counts[name] = db.execute(
                        'SELECT count(*) FROM "' + name.replace('"', '""') + '"'
                    ).fetchone()[0]
                print(f"BACKUP: OK {counts}")
        else:
            if args.target is None:
                parser.error("create and restore require a separate target")
            print(f"BACKUP: OK {verified_copy(args.source, args.target)}")
    except (OSError, sqlite3.Error, ValueError) as exc:
        print(f"BACKUP: FAIL {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
