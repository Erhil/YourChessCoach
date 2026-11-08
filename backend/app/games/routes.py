import io
from typing import Literal

import chess.pgn
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.auth.deps import UserId
from app.db import TRAINING_GAME, Db
from app.mistakes.events import GameError, record_game_errors, validate_game_moves

router = APIRouter(prefix="/api/games")

MAX_PLIES = 600


class GameIn(BaseModel):
    expected_login: str | None = Field(default=None, max_length=100)
    client_id: str | None = Field(None, min_length=1, max_length=100)
    pgn: str = Field(max_length=20000)
    player_color: Literal["white", "black"]
    level: int | None = None
    result: Literal["1-0", "0-1", "1/2-1/2", "*"]
    termination: (
        # The values the frontend sends; "abandoned": a new game started over an unfinished one.
        Literal[
            "checkmate",
            "stalemate",
            "threefold",
            "fifty_moves",
            "insufficient",
            "resign",
            "abandoned",
        ]
        | None
    ) = None
    # The player's blunders in the game; old clients do not send it.
    blunders: int | None = Field(None, ge=0, le=MAX_PLIES)
    # Takebacks and coach hints; old clients do not send them.
    takebacks: int = Field(0, ge=0, le=MAX_PLIES)
    hints: int = Field(0, ge=0, le=MAX_PLIES)
    errors: list[GameError] = Field(default_factory=list, max_length=MAX_PLIES)


def player_move_count(plies: int, player_color: str, initial_turn: chess.Color) -> int:
    return (plies + ((player_color == "white") == initial_turn)) // 2


@router.post("", status_code=201)
def create_game(body: GameIn, db: Db, user_id: UserId) -> dict:
    if body.expected_login is not None:
        owner = db.execute("SELECT login FROM users WHERE id = ?", (user_id,)).fetchone()
        if owner["login"] != body.expected_login:
            raise HTTPException(
                409, "Профиль изменился. Войдите в исходный профиль для сохранения."
            )
    game = chess.pgn.read_game(io.StringIO(body.pgn))
    if game is None or game.errors:
        raise HTTPException(422, "PGN does not parse")
    mainline = list(game.mainline_moves())
    moves = len(mainline)
    if moves == 0:
        raise HTTPException(422, "PGN must contain at least one move")
    if moves > MAX_PLIES:
        raise HTTPException(422, f"PGN is longer than {MAX_PLIES} plies")
    start = game.board()
    validate_game_moves(start, mainline)
    player_moves = player_move_count(moves, body.player_color, start.turn)
    if body.blunders is not None and body.blunders > player_moves:
        raise HTTPException(422, "Blunders exceed player moves")
    snapshot = (
        body.player_color,
        body.level,
        body.result,
        body.termination,
        body.pgn,
        moves,
        body.takebacks,
        body.hints,
    )
    with db:
        # The insert acquires the write lock before we inspect an existing game.
        cur = db.execute(
            "INSERT INTO games (user_id, player_color, level, result, termination, pgn, moves_count,"
            " takebacks, hints, blunders, client_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(user_id, client_id) DO NOTHING",
            (user_id, *snapshot, body.blunders, body.client_id),
        )
        game_id = cur.lastrowid
        if cur.rowcount == 0:
            row = db.execute(
                "SELECT id, player_color, level, result, termination, pgn, moves_count, takebacks,"
                " hints FROM games WHERE user_id = ? AND client_id = ?",
                (user_id, body.client_id),
            ).fetchone()
            if tuple(row)[1:] != snapshot:
                raise HTTPException(409, "Другая партия уже сохранена с этим идентификатором.")
            game_id = row["id"]
            if body.blunders is not None:
                db.execute(
                    "UPDATE games SET blunders = ? WHERE id = ? AND blunders IS NULL",
                    (body.blunders, game_id),
                )
        record_game_errors(
            db, user_id, game_id, "play", start, mainline, body.player_color, body.errors
        )
    return {"id": game_id}


@router.get("")
def list_games(db: Db, user_id: UserId) -> list[dict]:
    rows = db.execute(
        "SELECT id, created_at, player_color, level, result, termination, moves_count,"
        f" takebacks, hints, {TRAINING_GAME} AS training"
        " FROM games WHERE user_id = ? ORDER BY id DESC LIMIT 100",
        (user_id,),
    ).fetchall()
    return [{**dict(r), "training": bool(r["training"])} for r in rows]
