#!/usr/bin/env python3
"""Idempotent download of the Lichess openings (a.tsv..e.tsv) into data/openings.tsv.

The files come from raw.githubusercontent.com: it has no API rate limit.
A second run does not download again. Delete data/openings.tsv to get a fresh copy.
Usage: python scripts/download_openings.py [OUT_PATH]
"""

import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "openings.tsv"
RAW = "https://raw.githubusercontent.com/lichess-org/chess-openings/master/"
FILES = [f"{c}.tsv" for c in "abcde"]
HEADER = "eco\tname\tpgn"


def fetch(name):
    req = urllib.request.Request(RAW + name, headers={"User-Agent": "chess-coach-downloader"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8")


def main(out=OUT):
    if out.is_file() and out.stat().st_size > len(HEADER) + 1:
        print(f"openings: OK {len(out.read_text(encoding='utf-8').splitlines()) - 1} (present)")
        return 0
    lines = [HEADER]
    for name in FILES:
        rows = fetch(name).splitlines()
        if not rows or rows[0].strip() != HEADER:
            raise RuntimeError(f"unexpected header in {name}")
        lines += [r for r in rows[1:] if r.strip()]
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".part")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    tmp.replace(out)
    print(f"openings: OK {len(lines) - 1}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else OUT))
    except (OSError, RuntimeError, ValueError) as ex:
        print(f"openings: FAIL {type(ex).__name__}: {ex}")
        sys.exit(1)
