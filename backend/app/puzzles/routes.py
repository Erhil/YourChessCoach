import random
import sqlite3
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Annotated

import chess
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.auth.deps import UserId
from app.db import Db
from app.mistakes.routes import add_card
from app.openings.names import ru_name
from app.puzzles.rating import START_RATING, score, update_rating
from app.puzzles.themes import OFFERED, theme_name

router = APIRouter(prefix="/api/puzzles")

MISSING = "База задач не найдена. Выполните: python scripts/import_puzzles.py"
WINDOWS = (150, 300, 600, None)  # None = any rating, the last resort
RECENT = 200
MIN_OPENING_PUZZLES = 200


def get_puzzles_db(request: Request) -> Iterator[sqlite3.Connection]:
    path = request.app.state.settings.puzzles_db_path
    if not path.is_file():
        raise HTTPException(503, MISSING)
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


PuzzlesDb = Annotated[sqlite3.Connection, Depends(get_puzzles_db)]


class AttemptIn(BaseModel):
    solved: bool
    used_hint: bool = False


def _theme_keys(row: sqlite3.Row) -> list[str]:
    return (row["themes"] or "").split()


def _scope_rating(db: sqlite3.Connection, user_id: int, scope: str) -> tuple[float, int]:
    row = db.execute(
        "SELECT rating, attempts FROM user_ratings WHERE user_id = ? AND scope = ?",
        (user_id, scope),
    ).fetchone()
    return (row["rating"], row["attempts"]) if row else (START_RATING, 0)


def format_puzzle(row: sqlite3.Row) -> dict:
    """The stored FEN is before the opponent's move: moves[0] is the opponent's, the rest is the solution."""
    moves = row["moves"].split()
    board = chess.Board(row["fen"])
    board.push_uci(moves[0])
    return {
        "id": row["id"],
        "fen": row["fen"],
        "opponent_move": moves[0],
        "solution": moves[1:],
        "rating": row["rating"],
        "themes": [{"key": k, "name": theme_name(k)} for k in _theme_keys(row)],
        "player_color": "white" if board.turn == chess.WHITE else "black",
    }


@router.get("/themes")
def list_themes(pdb: PuzzlesDb) -> list[dict]:
    rows = pdb.execute("SELECT theme, COUNT(*) AS n FROM puzzle_themes GROUP BY theme").fetchall()
    result = [{"key": r["theme"], "name": theme_name(r["theme"]), "count": r["n"]} for r in rows]
    return sorted((t for t in result if t["key"] in OFFERED), key=lambda t: t["name"])


@lru_cache(maxsize=2)
def _opening_counts(path: str, mtime: float) -> dict[str, int]:
    """Opening families (the first Lichess tag) with enough puzzles; cached per db file version."""
    conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT CASE WHEN instr(opening_tags, ' ') > 0"
            " THEN substr(opening_tags, 1, instr(opening_tags, ' ') - 1) ELSE opening_tags END"
            " AS fam, COUNT(*) AS n FROM puzzles WHERE opening_tags != '' GROUP BY fam"
        ).fetchall()
    finally:
        conn.close()
    return {fam: n for fam, n in rows if n >= MIN_OPENING_PUZZLES}


def _families(request: Request) -> dict[str, int]:
    path = request.app.state.settings.puzzles_db_path
    return _opening_counts(str(path), path.stat().st_mtime)


@router.get("/openings")
def list_openings(request: Request, pdb: PuzzlesDb) -> list[dict]:
    counts = _families(request)
    return [
        {"key": k, "name": ru_name(k.replace("_", " ")), "count": n}
        for k, n in sorted(counts.items(), key=lambda kv: -kv[1])
    ]


@router.get("/next")
def next_puzzle(
    request: Request,
    db: Db,
    user_id: UserId,
    pdb: PuzzlesDb,
    theme: str | None = None,
    opening: str | None = None,
) -> dict:
    if theme is not None and theme not in OFFERED:
        raise HTTPException(404, "Неизвестная тема")
    if opening is not None and opening not in _families(request):
        raise HTTPException(404, "Неизвестный дебют")
    rating, n = _scope_rating(db, user_id, theme) if theme else (START_RATING, 0)
    if n == 0:
        rating, _ = _scope_rating(db, user_id, "overall")
    recent = [
        r[0]
        for r in db.execute(
            "SELECT puzzle_id FROM puzzle_attempts WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, RECENT),
        )
    ]
    for window in WINDOWS:
        where: list[str] = []
        args: list = []
        if theme:
            where.append("id IN (SELECT puzzle_id FROM puzzle_themes WHERE theme = ?)")
            args.append(theme)
        if opening:
            where.append("(opening_tags = ? OR substr(opening_tags, 1, ?) = ?)")
            args += [opening, len(opening) + 1, opening + " "]
        if window is not None:
            where.append("rating BETWEEN ? AND ?")
            args += [rating - window, rating + window]
        if recent:
            where.append(f"id NOT IN ({','.join('?' * len(recent))})")
            args += recent
        sql = "SELECT * FROM puzzles" + (" WHERE " + " AND ".join(where) if where else "")
        rows = pdb.execute(sql, args).fetchall()
        if rows:
            return {**format_puzzle(random.choice(rows)), "user_rating": round(rating)}
    raise HTTPException(404, "Подходящих задач не нашлось")


@router.post("/{puzzle_id}/attempt")
def attempt(puzzle_id: str, body: AttemptIn, db: Db, user_id: UserId, pdb: PuzzlesDb) -> dict:
    row = pdb.execute("SELECT * FROM puzzles WHERE id = ?", (puzzle_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Задача не найдена")
    result = score(body.solved, body.used_hint)
    scopes = ["overall", *(k for k in _theme_keys(row) if k in OFFERED)]
    new: dict[str, float] = {}
    before = after = 0.0
    with db:
        for scope in scopes:
            old, n = _scope_rating(db, user_id, scope)
            new[scope] = update_rating(old, n, row["rating"], result)
            db.execute(
                "INSERT INTO user_ratings (user_id, scope, rating, attempts) VALUES (?, ?, ?, 1)"
                " ON CONFLICT(user_id, scope) DO UPDATE SET rating = excluded.rating, attempts = attempts + 1",
                (user_id, scope, new[scope]),
            )
            if scope == "overall":
                before, after = old, new[scope]
        db.execute(
            "INSERT INTO puzzle_attempts (user_id, puzzle_id, solved, used_hint, puzzle_rating,"
            " rating_before, rating_after) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, puzzle_id, body.solved, body.used_hint, row["rating"], before, after),
        )
    if not body.solved:
        moves = row["moves"].split()
        board = chess.Board(row["fen"])
        board.push_uci(moves[0])
        motif = next((k for k in _theme_keys(row) if k in OFFERED), None)
        add_card(db, user_id, "puzzle", puzzle_id, board.fen(), moves[1], None, motif)
    return {
        "rating_before": round(before),
        "rating_after": round(after),
        "delta": round(after - before),
        "themes": [
            {"key": k, "name": theme_name(k), "rating": round(v)}
            for k, v in new.items()
            if k != "overall"
        ],
    }


@router.get("/rating")
def rating(db: Db, user_id: UserId) -> dict:
    overall, attempts = _scope_rating(db, user_id, "overall")
    rows = db.execute(
        "SELECT scope, rating, attempts FROM user_ratings WHERE user_id = ? AND scope != 'overall'",
        (user_id,),
    ).fetchall()
    themes = [
        {
            "key": r["scope"],
            "name": theme_name(r["scope"]),
            "rating": round(r["rating"]),
            "attempts": r["attempts"],
        }
        for r in rows
    ]
    return {
        "overall": round(overall),
        "attempts": attempts,
        "themes": sorted(themes, key=lambda t: t["name"]),
    }
