import io
from typing import Literal

import chess
import chess.pgn
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from app.auth.deps import UserId
from app.coach.classify import ORDER
from app.coach.explain import explain_facts
from app.coach.facts import build_facts
from app.db import Db
from app.engines.pool import EngineUnavailableError
from app.mistakes.routes import add_card
from app.review.analysis import review_moves
from app.security import ENGINE_HEAVY

router = APIRouter()

MAX_PLIES = 300
MAX_MOMENTS = 5
BAD = ORDER[ORDER.index("inaccuracy") :]


class ReviewRequest(BaseModel):
    pgn: str | None = Field(None, max_length=20000)
    side: Literal["white", "black"] | None = None
    game_id: int | None = None

    @model_validator(mode="after")
    def _one_source(self) -> "ReviewRequest":
        if (self.pgn is None) == (self.game_id is None):
            raise ValueError("send either pgn or game_id")
        return self


def parse_pgn(text: str) -> tuple[chess.Board, list[chess.Move]]:
    game = chess.pgn.read_game(io.StringIO(text))
    if game is None or game.errors:
        raise HTTPException(422, "PGN does not parse")
    moves = list(game.mainline_moves())
    if not moves:
        raise HTTPException(422, "PGN must contain at least one move")
    if len(moves) > MAX_PLIES:
        raise HTTPException(422, f"PGN is longer than {MAX_PLIES} plies")
    return game.board(), moves


@router.post("/api/review", dependencies=ENGINE_HEAVY)
def review(body: ReviewRequest, request: Request, db: Db, user_id: UserId) -> dict:
    side = body.side or "white"
    pgn = body.pgn
    if body.game_id is not None:
        row = db.execute(
            "SELECT pgn, player_color FROM games WHERE id = ? AND user_id = ?",
            (body.game_id, user_id),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Game not found")
        pgn, side = row["pgn"], row["player_color"]
    start, moves = parse_pgn(pgn)
    pool, settings = request.app.state.pool, request.app.state.settings
    try:
        rows = review_moves(pool, start, moves, settings)
        bad = [r for r in rows if r["color"] == side and r["classification"] in BAD]
        bad = sorted(bad, key=lambda r: r["drop"], reverse=True)
        moments = []
        for r in bad:
            if len(moments) == MAX_MOMENTS:
                break
            facts = build_facts(
                pool, chess.Board(r["fen_before"]), chess.Move.from_uci(r["uci"]), settings
            )
            if facts.classification not in BAD:  # deeper search says the move is fine
                continue
            moments.append(
                {
                    "ply": r["ply"],
                    "san": r["san"],
                    "classification": facts.classification,
                    "facts": facts,
                    "explanation": explain_facts(facts, db, request.app.state.llm, settings),
                }
            )
        moments.sort(key=lambda m: m["ply"])
        if body.game_id is not None:
            for m in moments:
                f = m["facts"]
                if f.classification in ("mistake", "blunder") and f.best_move:
                    motif = (f.motifs_missed or f.motifs_against or [None])[0]
                    add_card(
                        db,
                        user_id,
                        "game",
                        f"{body.game_id}:{m['ply']}",
                        f.fen_before,
                        f.best_move.uci,
                        f.classification,
                        motif.kind if motif else None,
                        f.player_move.uci,
                    )
    except EngineUnavailableError as exc:
        raise HTTPException(503, str(exc)) from exc
    summary = {
        k: sum(1 for r in rows if r["color"] == side and r["classification"] == k) for k in BAD
    }
    if body.game_id is not None:
        db.execute(
            "UPDATE games SET blunders = ? WHERE id = ? AND user_id = ?",
            (summary["blunder"], body.game_id, user_id),
        )
        db.commit()
    for r in rows:
        del r["drop"]
    return {"side": side, "moves": rows, "key_moments": moments, "summary": summary}
