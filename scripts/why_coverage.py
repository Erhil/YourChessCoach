"""Share of bad moves whose explanation names no cause (only "лучше было X").

Two sets: the bench (backend/tests/fixtures/bench.json, mostly tactics) and N random quiet
moves in opening positions from data/openings.tsv (seeded). "before" = the same facts without
reasons, so the number shows what the reasons add. For the bench the stored old facts are
counted too.
Run: python scripts/why_coverage.py [N]   (needs Stockfish)
"""

import io
import json
import random
import sys
from pathlib import Path

import chess
import chess.pgn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.coach.facts import build_facts
from app.coach.schema import CoachFacts
from app.coach.templates import explain
from app.config import settings
from app.engines.pool import EnginePool

BENCH = ROOT / "backend" / "tests" / "fixtures" / "bench.json"
OPENINGS = ROOT / "data" / "openings.tsv"
BAD = ("inaccuracy", "mistake", "blunder")


def has_cause(f: CoachFacts) -> bool:
    return bool(
        (f.material.change < 0 and f.material.lost)
        or f.motifs_against
        or f.motifs_missed
        or f.allowed_mate_in
        or f.missed_mate_in
        or f.threat
        or f.reasons_against
        or f.reasons_missed
    )


def share(items: list[CoachFacts]) -> str:
    bad = [f for f in items if f.classification in BAD]
    none = [f for f in bad if not has_cause(f)]
    return f"{len(none)}/{len(bad)} = {100 * len(none) / max(1, len(bad)):.0f}%"


def stripped(f: CoachFacts) -> CoachFacts:
    return f.model_copy(update={"reasons_against": [], "reasons_missed": []})


def quiet_moves(n: int) -> list[tuple[str, chess.Board, chess.Move]]:
    rng = random.Random(7)
    rows = OPENINGS.read_text(encoding="utf-8").splitlines()[1:]
    out = []
    while len(out) < n:
        pgn = rng.choice(rows).split("\t")[2]
        game = chess.pgn.read_game(io.StringIO(pgn))
        moves = list(game.mainline_moves())
        board = game.board()
        for mv in moves[: rng.randint(min(2, len(moves)), len(moves))]:
            board.push(mv)
        quiet = [m for m in board.legal_moves if not board.is_capture(m)]
        if quiet and not board.is_game_over():
            move = rng.choice(quiet)
            out.append((f"quiet-{len(out)}", board.copy(), move))
    return out


def run(pool: EnginePool, items: list[tuple[str, chess.Board, chess.Move]], show: bool):
    facts = []
    for name, board, move in items:
        f = build_facts(pool, board, move)
        facts.append(f)
        if show and f.classification in BAD and not f.material.lost:
            print(f"[{name}] {board.fen()} {move.uci()}", f"  {explain(f)}", sep="\n")
    return facts


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    bench = json.loads(BENCH.read_text(encoding="utf-8"))
    stored = [CoachFacts.model_validate(i["facts"]) for i in bench]
    pool = EnginePool(settings.engines_dir, 1, 2, 64)
    try:
        items = [
            (i["id"], chess.Board(i["fen"]), chess.Move.from_uci(i["move_uci"])) for i in bench
        ]
        rebuilt = run(pool, items, show=False)
        quiet = run(pool, quiet_moves(n), show=True)
    finally:
        pool.close()
    print("bench, stored old facts:      ", share(stored))
    print("bench, without reasons:       ", share([stripped(f) for f in rebuilt]))
    print("bench, with reasons:          ", share(rebuilt))
    print(f"{n} quiet moves, without reasons:", share([stripped(f) for f in quiet]))
    print(f"{n} quiet moves, with reasons:   ", share(quiet))


if __name__ == "__main__":
    main()
