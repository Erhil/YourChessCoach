import re
from functools import lru_cache
from pathlib import Path

import chess

MOVE_NUMBER = re.compile(r"\d+\.+")
MAX_NEXT = 8


@lru_cache(maxsize=2)
def load_openings(path: Path) -> dict[str, tuple[str, str]]:
    """Map the position (EPD) after each opening's moves to (eco, name)."""
    result: dict[str, tuple[str, str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines()[1:]:
        eco, name, pgn = line.split("\t")
        board = chess.Board()
        for san in MOVE_NUMBER.sub(" ", pgn).split():
            board.push_san(san)
        result.setdefault(board.epd(), (eco, name))
    return result


def find_opening(path: Path, moves: list[str]) -> dict | None:
    """The longest known opening the game passes through, or None.

    `exact` tells whether the position after the last move is itself a book position."""
    known = load_openings(path)
    board = chess.Board()
    found = None
    exact = False
    for uci in moves:
        board.push_uci(uci)
        exact = board.epd() in known
        found = known.get(board.epd(), found)
    return {"eco": found[0], "name": found[1], "exact": exact} if found else None


@lru_cache(maxsize=2)
def load_lines(path: Path) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    """Every opening of the file as (eco, name, SAN moves), in file order."""
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines()[1:]:
        eco, name, pgn = line.split("\t")
        rows.append((eco, name, tuple(MOVE_NUMBER.sub(" ", pgn).split())))
    return tuple(rows)


def family_of(name: str) -> str:
    """The family key of an opening name: the part before ":" without apostrophes."""
    return name.partition(":")[0].replace("'", "")


def opening_card(path: Path, moves: list[str]) -> dict | None:
    """Name, line and one-move continuations of the opening the game is in, or None."""
    found = find_opening(path, moves)
    if not found:
        return None
    lines = load_lines(path)
    line = next(r[2] for r in lines if (r[0], r[1]) == (found["eco"], found["name"]))
    n = len(line)
    seen: dict[str, dict] = {}
    for eco, name, sans in sorted(lines, key=lambda r: len(r[2])):
        if len(sans) > n and sans[:n] == line and sans[n] not in seen:
            board = chess.Board()
            for san in line:
                board.push_san(san)
            seen[sans[n]] = {
                "san": sans[n],
                "uci": board.push_san(sans[n]).uci(),
                "eco": eco,
                "name": name,
            }
    return {**found, "line_san": list(line), "continuations": list(seen.values())[:MAX_NEXT]}
