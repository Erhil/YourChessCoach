"""In-game hint: the opponent's threat (null move) and the engine's best move."""

from collections import Counter

import chess

from app.coach.facts import find_threat
from app.coach.templates import _items
from app.engines.pool import EnginePool


def build_hint(pool: EnginePool, board: chess.Board, depth: int) -> dict:
    """`threat` is the opponent's best move if we passed, only when it wins material or mates."""
    _, lines = pool.analyse(board, depth)
    best = chess.Move.from_uci(lines[0]["pv_uci"][0])
    piece = board.piece_at(best.from_square)
    found = find_threat(pool, board, depth)
    threat = None
    if found is not None:
        t = found[1]
        # What the threat wins, ready for the sentence "... и забрать <wins>"; None for a mate.
        wins = _items(Counter(t.wins), "acc") if t.wins and not t.mate_in else None
        threat = {"san": t.move_san, "uci": found[0], "wins": wins, "mate": bool(t.mate_in)}
    return {
        "threat": threat,
        "best": {
            "san": board.san(best),
            "uci": best.uci(),
            "piece": piece.symbol().upper() if piece else "",
        },
    }
