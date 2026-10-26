import chess
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from app.engines.pool import EngineUnavailableError
from app.security import ENGINE_HEAVY

router = APIRouter()

MAX_DEPTH = 20
MAX_MOVETIME_MS = 3000  # the search also stops at this time, when only a depth is sent


class AnalyzeRequest(BaseModel):
    fen: str = Field(max_length=100)
    depth: int | None = Field(None, ge=1, le=MAX_DEPTH)
    movetime_ms: int | None = Field(None, ge=10, le=MAX_MOVETIME_MS)
    multipv: int = Field(1, ge=1, le=5)

    @field_validator("fen")
    @classmethod
    def _valid_fen(cls, fen: str) -> str:
        try:
            board = chess.Board(fen)
        except ValueError as exc:
            raise ValueError(f"invalid FEN: {exc}") from exc
        if not board.is_valid():
            raise ValueError("invalid position")
        return fen


@router.post("/api/analyze", dependencies=ENGINE_HEAVY)
def analyze(body: AnalyzeRequest, request: Request) -> dict:
    board = chess.Board(body.fen)
    movetime_ms = body.movetime_ms
    if movetime_ms is None:
        movetime_ms = (
            request.app.state.settings.analysis_movetime_ms
            if body.depth is None
            else MAX_MOVETIME_MS
        )
    try:
        depth, lines = request.app.state.pool.analyse(board, body.depth, movetime_ms, body.multipv)
    except EngineUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "fen": body.fen,
        "turn": "white" if board.turn else "black",
        "depth": depth,
        "lines": lines,
    }
