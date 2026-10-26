"""Download the Lichess puzzle database (Parquet, Hugging Face, CC0) into data/puzzles-src/.

Idempotent: a complete file (size and SHA-256 match) is skipped. Incomplete downloads resume.
"""

import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = "Lichess/chess-puzzles"
API = f"https://huggingface.co/api/datasets/{REPO}"
FILE_URL = f"https://huggingface.co/datasets/{REPO}/resolve/main/"
DEST = Path(__file__).resolve().parent.parent / "data" / "puzzles-src"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def head(url: str) -> tuple[int, str]:
    """Return (size, SHA-256). The hash is in X-Linked-ETag of the redirect response."""
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        r = opener.open(urllib.request.Request(url, method="HEAD"), timeout=60)
    except urllib.error.HTTPError as e:
        r = e
        if e.code not in (301, 302, 307, 308):
            raise
    h = r.headers
    return int(h["X-Linked-Size"]), h["X-Linked-ETag"].strip('"')


def fetch(name: str) -> bool:
    """Download one file; return True if bytes were downloaded."""
    url = FILE_URL + name
    total, digest = head(url)
    dest = DEST / Path(name).name
    if dest.exists() and dest.stat().st_size == total and sha256(dest) == digest:
        print(f"up to date: {dest.name} ({total} bytes)")
        return False
    tmp = dest.with_name(dest.name + ".part")
    have = tmp.stat().st_size if tmp.exists() else 0
    if have > total:
        tmp.unlink()
        have = 0
    if have < total:
        req = urllib.request.Request(url, headers={"Range": f"bytes={have}-"} if have else {})
        with urllib.request.urlopen(req, timeout=60) as r:
            if have and r.status != 206:
                have = 0  # server ignored Range: restart
            with open(tmp, "ab" if have else "wb") as f:
                while chunk := r.read(1 << 20):
                    f.write(chunk)
    if tmp.stat().st_size != total:
        raise RuntimeError(
            f"{dest.name}: size {tmp.stat().st_size} != {total}; run again to resume"
        )
    if sha256(tmp) != digest:
        tmp.unlink()
        raise RuntimeError(f"{dest.name}: SHA-256 mismatch; run again")
    tmp.replace(dest)
    print(f"downloaded {dest.name} ({total} bytes)")
    return True


def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(API, timeout=60) as r:
            names = [s["rfilename"] for s in json.load(r)["siblings"]]
        names = [n for n in names if n.startswith("data/") and n.endswith(".parquet")]
        if not names:
            raise RuntimeError("no .parquet files listed by the API")
        n = sum(fetch(name) for name in names)
        print(f"puzzles download: OK {len(names)} files, {n} downloaded")
        return 0
    except (OSError, RuntimeError, KeyError, ValueError) as e:
        print(f"puzzles download: FAIL {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
