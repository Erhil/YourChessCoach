"""Record exact occurrences separately from the cards used for practice."""

import sqlite3
from typing import Literal

import chess
from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.mistakes.routes import add_card
from app.mistakes.srs import now_utc


class GameError(BaseModel):
    ply: int = Field(ge=1)
    best_uci: str = Field(max_length=10)
    classification: Literal["mistake", "blunder"]
    motif: str | None = Field(None, max_length=64)
    best_line: list[str] = Field(default_factory=list, max_length=32)


def validate_game_moves(start: chess.Board, moves: list[chess.Move]) -> None:
    board = start.copy(stack=False)
    for move in moves:
        if not board.is_legal(move):
            raise HTTPException(422, "PGN contains an illegal move")
        board.push(move)


def record_event(
    db: sqlite3.Connection,
    user_id: int,
    origin: Literal["play", "review", "puzzle"],
    source_id: int,
    ply: int,
    board: chess.Board,
    played_uci: str | None,
    continuation: list[str],
    classification: str | None,
    motif: str | None,
    *,
    puzzle_id: str | None = None,
) -> None:
    """The caller holds a write transaction. A delivered occurrence is immutable."""
    game_id = source_id if origin != "puzzle" else None
    attempt_id = source_id if origin == "puzzle" else None
    if db.execute(
        "SELECT 1 FROM mistake_events WHERE user_id = ? AND game_id IS ?"
        " AND attempt_id IS ? AND ply = ?",
        (user_id, game_id, attempt_id, ply),
    ).fetchone():
        return

    fen, best_uci = board.fen(), continuation[0]
    if puzzle_id is not None:
        source = "puzzle"
        ref = f"{puzzle_id}:{ply}:{played_uci or '-'}:{fen}:{best_uci}"
        recurrence = True
    else:
        source = "game"
        ref = f"{game_id}:{ply}"
        legacy = db.execute(
            "SELECT id, fen, best_uci, played_uci FROM mistakes"
            " WHERE user_id = ? AND source = 'game' AND ref = ?",
            (user_id, ref),
        ).fetchone()
        if legacy and (legacy["fen"], legacy["best_uci"], legacy["played_uci"]) == (
            fen,
            best_uci,
            played_uci,
        ):
            # A legacy saved-review card identifies this exact game move.
            recurrence = False
        else:
            existing = db.execute(
                "SELECT c.ref, MAX(e.game_id) OVER () AS latest_game_id"
                " FROM mistake_events e JOIN mistakes c ON c.id = e.card_id"
                " WHERE e.user_id = ? AND e.game_id IS NOT NULL AND e.fen = ?"
                " AND e.played_uci = ? ORDER BY e.id LIMIT 1",
                (user_id, fen, played_uci),
            ).fetchone()
            ref = existing["ref"] if existing else f"event:{ref}"
            # A late result for an older game must not reset a newer occurrence's card.
            recurrence = existing is not None and game_id > existing["latest_game_id"]
    card_id, created = add_card(
        db, user_id, source, ref, fen, best_uci, classification, motif, played_uci
    )
    if recurrence and not created:
        db.execute(
            "UPDATE mistakes SET due_at = ?, streak = 0, learned_at = NULL,"
            " review_version = review_version + 1 WHERE id = ?",
            (now_utc(), card_id),
        )
    db.execute(
        "INSERT INTO mistake_events (user_id, game_id, attempt_id, ply, card_id, origin,"
        " start_fen, fen, prefix_uci, played_uci, best_uci, continuation_uci, classification, motif)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            user_id,
            game_id,
            attempt_id,
            ply,
            card_id,
            origin,
            board.root().fen(),
            fen,
            " ".join(move.uci() for move in board.move_stack),
            played_uci,
            best_uci,
            " ".join(continuation),
            classification,
            motif,
        ),
    )


def record_game_errors(
    db: sqlite3.Connection,
    user_id: int,
    game_id: int,
    origin: Literal["play", "review"],
    start: chess.Board,
    moves: list[chess.Move],
    player_color: str,
    errors: list[GameError],
) -> None:
    errors_by_ply = {error.ply: error for error in errors}
    if len(errors_by_ply) != len(errors) or any(ply > len(moves) for ply in errors_by_ply):
        raise HTTPException(422, "Invalid or repeated game error ply")
    if not errors:
        return
    board = start.copy()
    for ply, played in enumerate(moves, 1):
        error = errors_by_ply.get(ply)
        if error is not None:
            if board.turn != (player_color == "white"):
                raise HTTPException(422, "Game error must be a player move")
            line = board.copy(stack=False)
            try:
                best = line.parse_uci(error.best_uci)
                if not best or best == played:
                    raise ValueError("best move must differ from the played move")
                if error.best_line:
                    continuation = []
                    for san in error.best_line:
                        move = line.push_san(san)
                        if not move:
                            raise ValueError("null move")
                        continuation.append(move.uci())
                    if continuation[0] != best.uci():
                        raise ValueError("line must start with the best move")
                else:
                    continuation = [best.uci()]
            except ValueError as exc:
                raise HTTPException(422, "Invalid game error continuation") from exc
            record_event(
                db,
                user_id,
                origin,
                game_id,
                ply,
                board,
                played.uci(),
                continuation,
                error.classification,
                error.motif,
            )
        board.push(played)
