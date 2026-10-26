"""Analyse every position of a game once and classify each move from the mover's view."""

from concurrent.futures import ThreadPoolExecutor

import chess

from app.coach.classify import classify, mover_view, score_win_chance, thresholds
from app.config import Settings
from app.engines.pool import EnginePool


def _mover(score: dict, color: chess.Color) -> tuple[float, int | None]:
    """Win chance and mate number of a White-view score, seen by `color`."""
    view = mover_view(score, color)
    return score_win_chance(view["cp"], view["mate"]), view["mate"]


def _final_score(board: chess.Board) -> dict:
    """Score of a finished game, White's view."""
    if board.is_checkmate():
        return {"cp": None, "mate": 0}
    return {"cp": 0, "mate": None}


def review_moves(pool: EnginePool, start: chess.Board, moves: list[chess.Move], s: Settings):
    """Return one dict per move: ply, san, uci, color, fen_before, eval_after, classification, drop."""
    boards = [start.copy(stack=False)]
    for move in moves:
        nxt = boards[-1].copy(stack=False)
        nxt.push(move)
        boards.append(nxt)
    with ThreadPoolExecutor(max_workers=max(1, s.engine_pool_size)) as ex:
        results = list(ex.map(lambda b: pool.analyse(b, s.review_depth)[1], boards))
    out = []
    for i, move in enumerate(moves):
        before, after = boards[i], boards[i + 1]
        color = before.turn
        best = results[i][0]
        score_after = results[i + 1][0]["score"] if results[i + 1] else _final_score(after)
        wc_b, mate_b = _mover(best["score"], color)
        wc_a, mate_a = (1.0, None) if after.is_checkmate() else _mover(score_after, color)
        is_best = after.is_checkmate() or move.uci() == best["pv_uci"][0]
        out.append(
            {
                "ply": i + 1,
                "san": before.san(move),
                "uci": move.uci(),
                "color": "white" if color == chess.WHITE else "black",
                "fen_before": before.fen(),
                "eval_after": score_after,
                "classification": classify(wc_b, wc_a, is_best, mate_b, mate_a, thresholds(s)),
                "drop": wc_b - wc_a,
            }
        )
    return out
