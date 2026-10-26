import os
import shutil
import sys
from pathlib import Path


def _is_binary(path: Path) -> bool:
    if not path.is_file():
        return False
    if sys.platform == "win32":
        return path.suffix.lower() == ".exe"
    return os.access(path, os.X_OK)


def find_binary(engines_dir: Path, name: str) -> Path | None:
    """Find an engine binary in engines_dir (two levels deep), then in PATH."""
    if engines_dir.is_dir():
        for pattern in (f"{name}*", f"*/{name}*", f"*/*/{name}*"):
            for path in sorted(engines_dir.glob(pattern)):
                if _is_binary(path):
                    return path
    found = shutil.which(name)
    return Path(found) if found else None


def find_maia_weights(engines_dir: Path, level: int) -> Path | None:
    """Find the Maia weight file for a level (maia-<level>.pb.gz) in engines_dir."""
    if not engines_dir.is_dir():
        return None
    for pattern in (f"maia-{level}.pb.gz", f"*/maia-{level}.pb.gz"):
        for path in sorted(engines_dir.glob(pattern)):
            if path.is_file():
                return path
    return None
