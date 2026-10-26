import chess
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, PrivateAttr, field_validator, model_validator

from app.engines.opponent import LEVELS
from app.engines.pool import EngineUnavailableError
from app.security import ENGINE_HEAVY

router = APIRouter()


class MoveRequest(BaseModel):
    moves: list[str] = Field(max_length=600)  # UCI moves from the standard start position
    level: int
    _board: chess.Board = PrivateAttr()

    @model_validator(mode="after")
    def _build_board(self) -> "MoveRequest":
        try:
            board = chess.Board()
            for uci in self.moves:
                board.push_uci(uci)  # raises ValueError on an illegal move
        except ValueError as exc:
            raise ValueError(f"invalid position: {exc}") from exc
        if not board.is_valid():
            raise ValueError("invalid position")
        if board.is_game_over():
            raise ValueError("game is over")
        self._board = board
        return self

    @field_validator("level")
    @classmethod
    def _known_level(cls, level: int) -> int:
        if level not in LEVELS:
            raise ValueError(f"unknown level {level}")
        return level


@router.get("/api/opponent/levels")
def levels(request: Request) -> list[dict]:
    opponent = request.app.state.opponent
    return [
        {"level": lvl, "label": f"{name} ({lvl})", "engine": opponent.engine_name(lvl)}
        for lvl, name in LEVELS.items()
    ]


@router.post("/api/opponent/move", dependencies=ENGINE_HEAVY)
def opponent_move(body: MoveRequest, request: Request) -> dict:
    board = body._board
    try:
        move, engine = request.app.state.opponent.move(board, body.level)
    except EngineUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"uci": move.uci(), "san": board.san(move), "engine": engine}
