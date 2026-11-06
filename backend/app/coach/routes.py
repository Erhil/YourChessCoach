from typing import Literal

import chess
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, PrivateAttr, model_validator

from app.coach import ask
from app.coach.explain import explain_facts
from app.coach.facts import build_facts
from app.coach.hint import build_hint
from app.coach.schema import CoachFacts
from app.coach.templates import explain
from app.db import Db
from app.engines.pool import EngineUnavailableError
from app.security import ENGINE_HEAVY

router = APIRouter()


class CoachMoveRequest(BaseModel):
    fen: str = Field(max_length=100)
    move: str = Field(max_length=10)
    help_level: int | None = Field(default=None, ge=1, le=5)
    _board: chess.Board = PrivateAttr()
    _move: chess.Move = PrivateAttr()

    @model_validator(mode="after")
    def _build(self) -> "CoachMoveRequest":
        try:
            board = chess.Board(self.fen)
            move = chess.Move.from_uci(self.move)
        except ValueError as exc:
            raise ValueError(f"invalid input: {exc}") from exc
        if not board.is_valid() or board.is_game_over():
            raise ValueError("invalid position")
        if move not in board.legal_moves:
            raise ValueError("illegal move")
        self._board, self._move = board, move
        return self


class AskRequest(CoachMoveRequest):
    question: Literal["why", "threat", "better", "free"]
    text: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _text(self) -> "AskRequest":
        if self.question == "free" and not (self.text or "").strip():
            raise ValueError("text is required for a free question")
        return self


class HintRequest(BaseModel):
    fen: str = Field(max_length=100)

    @model_validator(mode="after")
    def _check(self) -> "HintRequest":
        try:
            board = chess.Board(self.fen)
        except ValueError as exc:
            raise ValueError(f"invalid input: {exc}") from exc
        if not board.is_valid() or board.is_game_over():
            raise ValueError("invalid position")
        return self


def _facts(body: CoachMoveRequest, request: Request) -> CoachFacts:
    try:
        return build_facts(
            request.app.state.pool, body._board, body._move, request.app.state.settings
        )
    except EngineUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/api/coach/hint", dependencies=ENGINE_HEAVY)
def coach_hint(body: HintRequest, request: Request) -> dict:
    try:
        return build_hint(
            request.app.state.pool, chess.Board(body.fen), request.app.state.settings.coach_depth
        )
    except EngineUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/api/coach/move", dependencies=ENGINE_HEAVY)
def coach_move(body: CoachMoveRequest, request: Request, db: Db) -> dict:
    facts = _facts(body, request)
    state = request.app.state
    level = body.help_level
    visible = (
        level is None
        or level == 5
        or (level >= 2 and facts.classification == "blunder")
        or (level >= 3 and facts.classification == "mistake")
    )
    return {
        "facts": facts,
        "explanation": explain_facts(facts, db, state.llm, state.settings)
        if visible
        else {"text": explain(facts), "source": "template", "model": None},
    }


@router.post("/api/coach/ask", dependencies=ENGINE_HEAVY)
def coach_ask(body: AskRequest, request: Request) -> dict:
    state = request.app.state
    text = (body.text or "").strip()
    facts = _facts(body, request)
    return ask.answer(facts, body.question, text, state.settings, state.pool)
