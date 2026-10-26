import io
from typing import Literal

import chess.pgn
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.auth.deps import UserId
from app.db import TRAINING_GAME, Db

router = APIRouter(prefix="/api/games")

MAX_PLIES = 600


class GameIn(BaseModel):
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


@router.post("", status_code=201)
def create_game(body: GameIn, db: Db, user_id: UserId) -> dict:
    game = chess.pgn.read_game(io.StringIO(body.pgn))
    moves = len(list(game.mainline_moves())) if game else 0
    if moves == 0:
        raise HTTPException(422, "PGN must contain at least one move")
    if moves > MAX_PLIES:
        raise HTTPException(422, f"PGN is longer than {MAX_PLIES} plies")
    with db:
        cur = db.execute(
            "INSERT INTO games (user_id, player_color, level, result, termination, pgn, moves_count,"
            " blunders, takebacks, hints) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                body.player_color,
                body.level,
                body.result,
                body.termination,
                body.pgn,
                moves,
                body.blunders,
                body.takebacks,
                body.hints,
            ),
        )
    return {"id": cur.lastrowid}


@router.get("")
def list_games(db: Db, user_id: UserId) -> list[dict]:
    rows = db.execute(
        "SELECT id, created_at, player_color, level, result, termination, moves_count,"
        f" takebacks, hints, {TRAINING_GAME} AS training"
        " FROM games WHERE user_id = ? ORDER BY id DESC LIMIT 100",
        (user_id,),
    ).fetchall()
    return [{**dict(r), "training": bool(r["training"])} for r in rows]
