import json
import random
import sqlite3
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Annotated

import chess
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth.deps import UserId
from app.db import Db
from app.mistakes.events import record_event
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


class AttemptDetails(BaseModel):
    # One-based learner turn, after the opponent's initial move.
    ply: int = Field(ge=1)
    played_uci: str | None = Field(max_length=10)
    first_uci: str | None = Field(max_length=10)
    revealed: bool
    elapsed_ms: int = Field(ge=0, le=2**53 - 1)


class AttemptIn(BaseModel):
    client_id: str | None = Field(None, min_length=1, max_length=100)
    expected_login: str | None = Field(None, max_length=100)
    solved: bool
    used_hint: bool = False
    details: AttemptDetails | None = None


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
    exclude: str | None = None,
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
        if exclude:
            where.append("id != ?")
            args.append(exclude)
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


def _attempt_position(
    row: sqlite3.Row, details: AttemptDetails, solved: bool
) -> tuple[chess.Board, list[str]]:
    moves = row["moves"].split()
    index = 2 * details.ply - 1
    if index >= len(moves):
        raise HTTPException(422, "Puzzle learner turn is outside the solution")
    board = chess.Board(row["fen"])
    try:
        for uci in moves[:index]:
            board.push_uci(uci)
        line = board.copy(stack=False)
        for uci in moves[index:]:
            line.push_uci(uci)
        if details.first_uci is not None and not board.parse_uci(details.first_uci):
            raise ValueError("null first move")
        if details.played_uci is None:
            if solved or not details.revealed or details.first_uci is not None:
                raise ValueError("only a direct reveal can omit the played move")
        else:
            played = board.parse_uci(details.played_uci)
            if not played:
                raise ValueError("null played move")
            after = board.copy(stack=False)
            after.push(played)
            is_mate = after.is_checkmate()
            matches = played.uci() == moves[index]
            accepted = matches or (is_mate and index >= len(moves) - 2)
            terminal = is_mate or index + 2 >= len(moves)
            if (solved and not (accepted and terminal)) or (not solved and accepted):
                raise ValueError("played move does not match the result")
    except ValueError as exc:
        raise HTTPException(422, "Invalid puzzle attempt details") from exc
    return board, moves[index:]


@router.post("/{puzzle_id}/attempt")
def attempt(puzzle_id: str, body: AttemptIn, db: Db, user_id: UserId, pdb: PuzzlesDb) -> dict:
    if body.expected_login is not None:
        owner = db.execute("SELECT login FROM users WHERE id = ?", (user_id,)).fetchone()
        if owner["login"] != body.expected_login:
            raise HTTPException(
                409, "Профиль изменился. Войдите в исходный профиль для сохранения."
            )
    row = pdb.execute("SELECT * FROM puzzles WHERE id = ?", (puzzle_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Задача не найдена")
    result = score(body.solved, body.used_hint)
    scopes = ["overall", *(k for k in _theme_keys(row) if k in OFFERED)]
    new: dict[str, float] = {}
    before = after = 0.0
    details = body.details
    details_json = details.model_dump_json() if details is not None else None
    with db:
        # Serialize the receipt check and all rating writes across connections.
        db.execute("BEGIN IMMEDIATE")
        if body.client_id:
            receipt = db.execute(
                "SELECT r.*, a.details FROM puzzle_receipts r"
                " LEFT JOIN puzzle_attempts a ON a.id = r.attempt_id"
                " WHERE r.user_id = ? AND r.client_id = ?",
                (user_id, body.client_id),
            ).fetchone()
            if receipt:
                prior = (
                    AttemptDetails.model_validate_json(receipt["details"])
                    if receipt["details"] is not None
                    else None
                )
                can_annotate = (
                    prior is not None and not body.solved and prior.played_uci is not None
                )
                same_details = details == prior
                if can_annotate and details is not None:
                    same_details = details.model_copy(update={"revealed": prior.revealed}) == prior
                if not same_details or (
                    receipt["puzzle_id"],
                    receipt["solved"],
                    receipt["used_hint"],
                ) != (
                    puzzle_id,
                    body.solved,
                    body.used_hint,
                ):
                    raise HTTPException(
                        409, "Этот идентификатор уже использован для другого результата"
                    )
                if can_annotate and details is not None and details.revealed and not prior.revealed:
                    db.execute(
                        "UPDATE puzzle_attempts SET details = ? WHERE id = ?",
                        (details_json, receipt["attempt_id"]),
                    )
                return json.loads(receipt["response"])
        position = _attempt_position(row, details, body.solved) if details else None
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
        attempt_row = db.execute(
            "INSERT INTO puzzle_attempts (user_id, puzzle_id, solved, used_hint, puzzle_rating,"
            " rating_before, rating_after, details) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                puzzle_id,
                body.solved,
                body.used_hint,
                row["rating"],
                before,
                after,
                details_json,
            ),
        )
        response = {
            "rating_before": round(before),
            "rating_after": round(after),
            "delta": round(after - before),
            "themes": [
                {"key": k, "name": theme_name(k), "rating": round(v)}
                for k, v in new.items()
                if k != "overall"
            ],
        }
        if not body.solved:
            motif = next((k for k in _theme_keys(row) if k in OFFERED), None)
            if details is not None and position is not None:
                board, continuation = position
                record_event(
                    db,
                    user_id,
                    "puzzle",
                    attempt_row.lastrowid,
                    details.ply,
                    board,
                    details.played_uci,
                    continuation,
                    None,
                    motif,
                    puzzle_id=puzzle_id,
                )
            else:
                moves = row["moves"].split()
                board = chess.Board(row["fen"])
                board.push_uci(moves[0])
                add_card(db, user_id, "puzzle", puzzle_id, board.fen(), moves[1], None, motif)
        if body.client_id:
            db.execute(
                "INSERT INTO puzzle_receipts"
                " (user_id, client_id, puzzle_id, solved, used_hint, response, attempt_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    user_id,
                    body.client_id,
                    puzzle_id,
                    body.solved,
                    body.used_hint,
                    json.dumps(response, ensure_ascii=False),
                    attempt_row.lastrowid,
                ),
            )
    return response


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
