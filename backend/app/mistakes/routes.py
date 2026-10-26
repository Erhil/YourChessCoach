import sqlite3
from typing import Literal

import chess
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.activity.days import Tz, local_day_utc, local_today, server_tz
from app.auth.deps import UserId
from app.coach.explain import explain_facts
from app.coach.facts import build_facts
from app.db import Db
from app.engines.pool import EngineUnavailableError
from app.mistakes.srs import DAILY_LIMIT, LEARNED_STREAK, now_utc, schedule
from app.security import ENGINE_HEAVY

router = APIRouter(prefix="/api/mistakes")


def add_card(
    db: sqlite3.Connection,
    user_id: int,
    source: str,
    ref: str,
    fen: str,
    best_uci: str,
    classification: str | None,
    motif: str | None,
    played_uci: str | None = None,
) -> tuple[int, bool]:
    """Insert a card due now. Return (id, created); a known (source, ref) is not added again."""
    best_san = chess.Board(fen).san(chess.Move.from_uci(best_uci))
    now = now_utc()
    with db:
        cur = db.execute(
            "INSERT OR IGNORE INTO mistakes (user_id, source, ref, fen, best_uci, best_san, classification,"
            " motif, played_uci, created_at, due_at, reviews, lapses)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)",
            (
                user_id,
                source,
                ref,
                fen,
                best_uci,
                best_san,
                classification,
                motif,
                played_uci,
                now,
                now,
            ),
        )
    row = db.execute(
        "SELECT id FROM mistakes WHERE user_id = ? AND source = ? AND ref = ?",
        (user_id, source, ref),
    )
    return row.fetchone()["id"], cur.rowcount == 1


def _board(fen: str, uci: str) -> tuple[chess.Board, chess.Move]:
    try:
        board, move = chess.Board(fen), chess.Move.from_uci(uci)
    except ValueError as exc:
        raise HTTPException(422, f"invalid input: {exc}") from exc
    if not board.is_valid() or board.is_game_over():
        raise HTTPException(422, "invalid position")
    if move not in board.legal_moves:
        raise HTTPException(422, "illegal move")
    return board, move


class PlayCard(BaseModel):
    source: Literal["play"]
    fen: str = Field(max_length=100)
    best_uci: str = Field(max_length=10)
    classification: Literal["mistake", "blunder"]
    motif: str | None = Field(None, max_length=64)
    played_uci: str | None = Field(None, max_length=10)  # None: an older client sends no move


class Answer(BaseModel):
    uci: str = Field(max_length=10)


@router.post("")
def create(body: PlayCard, db: Db, user_id: UserId) -> dict:
    _board(body.fen, body.best_uci)
    if body.played_uci is not None:
        _board(body.fen, body.played_uci)
    card_id, created = add_card(
        db,
        user_id,
        "play",
        body.fen,
        body.fen,
        body.best_uci,
        body.classification,
        body.motif,
        body.played_uci,
    )
    return {"id": card_id, "created": created}


@router.get("/next")
def next_card(db: Db, user_id: UserId, tz: int | None = Tz) -> dict:
    tz = server_tz() if tz is None else tz
    now = now_utc()
    # Deck answers of the local today; the UTC range uses the index card_reviews_user.
    start, end = local_day_utc(local_today(now, tz), tz)
    reviewed = db.execute(
        "SELECT COUNT(*) FROM card_reviews WHERE user_id = ? AND created_at >= ? AND created_at < ?",
        (user_id, start, end),
    ).fetchone()[0]
    where = "user_id = ? AND due_at <= ? AND learned_at IS NULL"
    due = db.execute(f"SELECT COUNT(*) FROM mistakes WHERE {where}", (user_id, now)).fetchone()[0]
    row = None
    if reviewed < DAILY_LIMIT:
        row = db.execute(
            f"SELECT * FROM mistakes WHERE {where} ORDER BY due_at, id LIMIT 1", (user_id, now)
        ).fetchone()
    card = None
    if row:
        board = chess.Board(row["fen"])
        played = row["played_uci"]
        card = {
            "id": row["id"],
            "fen": row["fen"],
            "side": "white" if board.turn == chess.WHITE else "black",
            "source": row["source"],
            "motif": row["motif"],
            "classification": row["classification"],
            "played_san": board.san(chess.Move.from_uci(played)) if played else None,
        }
    return {"card": card, "due": due, "today": {"reviewed": reviewed, "limit": DAILY_LIMIT}}


@router.post("/{card_id}/answer", dependencies=ENGINE_HEAVY)
def answer(card_id: int, body: Answer, request: Request, db: Db, user_id: UserId) -> dict:
    row = db.execute(
        "SELECT * FROM mistakes WHERE id = ? AND user_id = ?", (card_id, user_id)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Card not found")
    board, move = _board(row["fen"], body.uci)
    try:
        facts = build_facts(request.app.state.pool, board, move, request.app.state.settings)
    except EngineUnavailableError as exc:
        raise HTTPException(503, str(exc)) from exc
    # "good" loses less than the inaccuracy threshold: the move is not a mistake (2.d3 after 1.e4 e5).
    correct = body.uci == row["best_uci"] or facts.classification in ("best", "good")
    streak, due_at, learned = schedule(row["streak"], correct)
    with db:
        db.execute(
            "UPDATE mistakes SET streak = ?, due_at = ?, learned_at = ?, reviews = reviews + 1,"
            " lapses = lapses + ? WHERE id = ?",
            (streak, due_at, due_at if learned else None, 0 if correct else 1, card_id),
        )
        db.execute(
            "INSERT INTO card_reviews (user_id, mistake_id, correct) VALUES (?, ?, ?)",
            (user_id, card_id, int(correct)),
        )
    state = request.app.state
    explanation = None if correct else explain_facts(facts, db, state.llm, state.settings)
    return {
        "correct": correct,
        "best_uci": row["best_uci"],
        "best_san": row["best_san"],
        "streak": streak,
        "left": max(0, LEARNED_STREAK - streak),
        "learned": learned,
        "due_at": due_at,
        "explanation": explanation,
    }


@router.get("/stats")
def stats(db: Db, user_id: UserId) -> dict:
    row = db.execute(
        "SELECT COUNT(*) AS total,"
        " COALESCE(SUM(learned_at IS NOT NULL), 0) AS learned,"
        " COALESCE(SUM(learned_at IS NULL AND due_at <= ?), 0) AS due FROM mistakes"
        " WHERE user_id = ?",
        (now_utc(), user_id),
    ).fetchone()
    return {"total": row["total"], "due": row["due"], "learned": row["learned"]}
