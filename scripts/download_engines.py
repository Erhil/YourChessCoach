#!/usr/bin/env python3
"""Idempotent download of Stockfish, lc0 and Maia weights into engines/ (lc0 is built on Linux)."""

import argparse
import gzip
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINES = ROOT / "engines"
WIN = sys.platform == "win32"
EXE = ".exe" if WIN else ""
MAIA_API = "https://api.github.com/repos/CSSLab/maia-chess/contents/maia_weights"
MAIA_FILES = [f"maia-{n}.pb.gz" for n in (1100, 1300, 1500, 1700, 1900)]
# Newest lc0 that builds with GCC 9 (Ubuntu 20.04): v0.32 needs C++20 (<span>, GCC 10+).
LC0_TAG = "v0.31.2"
LC0_MESON_OPTIONS = [  # CPU only, Eigen and zlib come as meson subprojects, static binary
    "--buildtype=release",
    "-Ddefault_library=static",
    "-Db_lto=false",  # GCC 9 LTO with many jobs needs make
    *(
        f"-D{o}=false"
        for o in (
            "gtest",
            "openblas",
            "mkl",
            "accelerate",
            "ispc",
            "opencl",
            "cudnn",
            "plain_cuda",
            "dx",
        )
    ),
]


def get(url, headers=None):
    h = {"User-Agent": "chess-coach-downloader", "Accept": "*/*"}
    h.update(headers or {})
    tok = os.environ.get("GITHUB_TOKEN")
    if tok and "api.github.com" in url:
        h["Authorization"] = f"Bearer {tok}"
    return urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=60)


def api(url):
    with get(url) as r:
        return json.load(r)


def sha(path, algo="sha256", git_blob=False):
    h = hashlib.new(algo)
    if git_blob:
        h.update(b"blob %d\0" % path.stat().st_size)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(path, size, digest=None, git_sha1=None):
    if not path.is_file() or path.stat().st_size != size:
        return False
    if digest and sha(path) != digest:
        return False
    return not git_sha1 or sha(path, "sha1", True) == git_sha1


def download(url, dest, size, digest=None, git_sha1=None):
    """Download to dest.part (resume with Range), check, rename. Skip if dest is complete."""
    if verify(dest, size, digest, git_sha1):
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    for _ in range(2):
        have = part.stat().st_size if part.exists() else 0
        if have > size:
            part.unlink()
            have = 0
        if have < size:
            print(f"  downloading {dest.name} ({size // 1024} KiB, from {have})", flush=True)
            hdr = {"Range": f"bytes={have}-"} if have else {}
            with get(url, hdr) as r:
                if have and r.status != 206:  # server ignored Range: start over
                    have = 0
                with part.open("ab" if have else "wb") as f:
                    shutil.copyfileobj(r, f, 1 << 20)
        if verify(part, size, digest, git_sha1):
            part.replace(dest)
            return True
        part.unlink(missing_ok=True)  # corrupt: retry from scratch once
    raise RuntimeError(f"size/hash mismatch for {dest.name}")


def extract(archive, out):
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            z.extractall(out)
    else:
        with tarfile.open(archive) as t:
            t.extractall(out, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))


def install_release(repo, pick, folder, finish):
    """Fetch the latest release asset chosen by pick(), unpack via finish(tmp, folder). Returns exe path."""
    marker = folder / ".installed"
    try:
        rel = api(f"https://api.github.com/repos/{repo}/releases/latest")
        asset = pick(rel["assets"])
        if asset is None:
            raise RuntimeError("no suitable asset in release " + rel["tag_name"])
    except Exception:
        if marker.exists():  # offline or rate limited: keep what is installed
            return Path(json.loads(marker.read_text(encoding="utf-8"))["exe"])
        raise
    if marker.exists():
        info = json.loads(marker.read_text(encoding="utf-8"))
        if info["asset"] == asset["name"] and Path(info["exe"]).is_file():
            return Path(info["exe"])
    folder.mkdir(parents=True, exist_ok=True)
    digest = (asset.get("digest") or "").removeprefix("sha256:") or None
    archive = folder / asset["name"]
    download(asset["browser_download_url"], archive, asset["size"], digest)
    tmp = folder / "_unpack"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    try:
        extract(archive, tmp)
        exe = finish(tmp, folder)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    archive.unlink(missing_ok=True)
    marker.write_text(json.dumps({"asset": asset["name"], "exe": str(exe)}), encoding="utf-8")
    return exe


def cpu_level():
    """2 = AVX2, 1 = SSE4.1 + POPCNT, 0 = generic."""
    if WIN:
        import ctypes

        f = ctypes.windll.kernel32.IsProcessorFeaturePresent
        return 2 if f(40) else 1 if f(37) and f(38) else 0
    flags = set()
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("flags"):
                flags = set(line.split(":", 1)[1].split())
                break
    except OSError:
        pass
    return 2 if "avx2" in flags else 1 if {"sse4_1", "popcnt"} <= flags else 0


def pick_stockfish(assets):
    osname = "windows" if WIN else "linux"
    ext = (".zip",) if WIN else (".tar", ".tar.gz", ".tgz")
    if platform.machine().lower() in ("arm64", "aarch64"):
        prefs = ["arm64"]
    else:
        # AVX2 CPU tries all builds; weaker CPUs skip builds they cannot run
        prefs = ["x86-64-avx2", "x86-64-sse41-popcnt", "x86-64-universal", "x86-64."][
            2 - cpu_level() :
        ]
    names = [a for a in assets if osname in a["name"] and a["name"].endswith(ext)]
    for p in prefs:
        for a in names:
            if p in a["name"]:
                return a
    return None


def finish_stockfish(tmp, folder):
    cands = [
        p
        for p in tmp.rglob("*")
        if p.is_file()
        and p.name.lower().startswith("stockfish")
        and (p.suffix.lower() == ".exe" if WIN else p.suffix == "")
    ]
    if not cands:
        raise RuntimeError("no stockfish executable in archive")
    exe = folder / f"stockfish{EXE}"
    shutil.copy2(max(cands, key=lambda p: p.stat().st_size), exe)
    exe.chmod(0o755)
    return exe


def pick_lc0(assets):
    cpu = [
        a
        for a in assets
        if "windows" in a["name"] and "cpu" in a["name"] and a["name"].endswith(".zip")
    ]
    for p in ("openblas", "dnnl", ""):
        for a in cpu:
            if p in a["name"]:
                return a
    return None


def finish_lc0(tmp, folder):
    exes = list(tmp.rglob("lc0.exe"))
    if not exes:
        raise RuntimeError("no lc0.exe in archive")
    for item in exes[0].parent.iterdir():
        dst = folder / item.name
        if dst.is_dir():
            shutil.rmtree(dst)
        shutil.move(str(item), str(dst))
    return folder / "lc0.exe"


def quiet(cmd, **kw):
    """Run cmd with captured output; on failure print the command and the last 40 lines."""
    pipe, err = subprocess.PIPE, subprocess.STDOUT
    r = subprocess.run(cmd, check=False, stdout=pipe, stderr=err, errors="replace", **kw)
    if r.returncode:
        print("  $ " + " ".join(map(str, cmd)), *r.stdout.splitlines()[-40:], sep="\n    ")
        raise subprocess.CalledProcessError(r.returncode, cmd)


def build_lc0():
    """Linux and macOS: build lc0 from source with the Eigen CPU backend."""
    folder = ENGINES / "lc0"
    exe, marker = folder / "lc0", folder / ".installed"
    if (
        marker.exists()
        and exe.is_file()
        and json.loads(marker.read_text(encoding="utf-8")).get("tag") == LC0_TAG
    ):
        return exe
    if not (shutil.which("git") and (shutil.which("c++") or shutil.which("g++"))):
        raise RuntimeError("install g++ and git (Debian/Ubuntu: sudo apt install g++ git)")
    py = sys.executable
    subprocess.run([py, "-m", "pip", "install", "-q", "meson", "ninja"], check=True)
    env = dict(os.environ)  # meson looks for ninja in PATH
    env["PATH"] = sysconfig.get_path("scripts") + os.pathsep + env.get("PATH", "")
    src = folder / f"src-{LC0_TAG}"
    shutil.rmtree(src, ignore_errors=True)
    print(f"  building lc0 {LC0_TAG} (2–5 min)…", flush=True)
    url = "https://github.com/LeelaChessZero/lc0"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", "--branch", LC0_TAG, url, str(src)], check=True
    )
    meson = [py, "-m", "mesonbuild.mesonmain"]
    quiet([*meson, "setup", "build", *LC0_MESON_OPTIONS], cwd=src, env=env)
    quiet([*meson, "compile", "-C", "build", "lc0"], cwd=src, env=env)
    shutil.copy2(src / "build" / "lc0", exe)
    exe.chmod(0o755)
    shutil.rmtree(src, ignore_errors=True)
    marker.write_text(json.dumps({"tag": LC0_TAG, "exe": str(exe)}), encoding="utf-8")
    return exe


def get_maia():
    out = ENGINES / "maia"
    if all((out / n).is_file() for n in MAIA_FILES):  # no API call: the limit is 60 per hour
        return len(MAIA_FILES)
    listing = {e["name"]: e for e in api(MAIA_API)}
    for name in MAIA_FILES:
        e = listing.get(name)
        if e is None:
            raise RuntimeError(f"{name} not found in repository")
        download(e["download_url"], out / name, e["size"], git_sha1=e["sha"])
        with gzip.open(out / name) as g:  # the gzip must be readable
            g.read(16)
    return len(MAIA_FILES)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", choices=["stockfish", "lc0", "maia"])
    only = ap.parse_args().only
    results = {}

    def run(key, fn):
        if only in (None, key):
            try:
                results[key] = "OK " + fn()
            except (
                OSError,
                RuntimeError,
                KeyError,
                ValueError,
                zipfile.BadZipFile,
                tarfile.TarError,
                subprocess.CalledProcessError,
            ) as ex:  # report per item, keep going
                results[key] = f"FAIL {type(ex).__name__}: {ex}"

    def lc0():
        if not WIN:  # lc0 releases have no Linux binary
            return str(build_lc0())
        return str(install_release("LeelaChessZero/lc0", pick_lc0, ENGINES / "lc0", finish_lc0))

    run(
        "stockfish",
        lambda: str(
            install_release(
                "official-stockfish/Stockfish",
                pick_stockfish,
                ENGINES / "stockfish",
                finish_stockfish,
            )
        ),
    )
    run("lc0", lc0)
    run("maia", lambda: f"{get_maia()} files")
    for k, v in results.items():
        print(f"{k}: {v}")
    return 1 if results.get("stockfish", "OK").startswith("FAIL") else 0


if __name__ == "__main__":
    sys.exit(main())
