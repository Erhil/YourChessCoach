"""Build backend/tests/fixtures/bench.json: mistakes of many types with stored CoachFacts.

Sources: backend/tests/fixtures/facts.json plus positions from data/puzzles.db.
Run: python scripts/make_bench.py   (needs Stockfish; takes a few minutes)
"""

import json
import random
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import chess

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.coach.facts import build_facts
from app.config import settings
from app.engines.pool import EnginePool

OUT = ROOT / "backend" / "tests" / "fixtures" / "bench.json"
KINDS_OF_CASES = {
    "queen_left_hanging": "hanging_piece",
    "allows_mate_in_1": "allowed_mate",
    "misses_knight_fork": "missed_fork",
    "best_move_wins_queen": "best_move",
    "misses_mate_in_1": "missed_mate",
    "queen_takes_defended_pawn": "losing_exchange",
    "ignores_mate_threat": "mate_threat_ignored",
    "small_inaccuracy_no_loss": "inaccuracy",
    "refutation_is_fork": "fork_against",
    "gives_checkmate": "checkmate_given",
    "gives_stalemate": "stalemate",
    "start_d4_is_best": "best_move",
}


def has(items, kind):
    return any(m.kind == kind for m in items)


def bad(f):
    return f.classification in ("mistake", "blunder")


# kind -> (puzzle theme, predicate on facts)
TARGETS = {
    "hanging_piece": ("hangingPiece", lambda f: bad(f) and has(f.motifs_against, "hanging_piece")),
    "fork_against": ("fork", lambda f: bad(f) and has(f.motifs_against, "fork")),
    "missed_fork": ("fork", lambda f: bad(f) and has(f.motifs_missed, "fork")),
    "pin": ("pin", lambda f: bad(f) and (has(f.motifs_against + f.motifs_missed, "pin"))),
    "skewer": ("skewer", lambda f: bad(f) and has(f.motifs_against + f.motifs_missed, "skewer")),
    "discovered_attack": (
        "discoveredAttack",
        lambda f: bad(f) and has(f.motifs_against + f.motifs_missed, "discovered_attack"),
    ),
    "back_rank": (
        "backRankMate",
        lambda f: (
            bad(f) and (has(f.motifs_against + f.motifs_missed, "back_rank") or f.allowed_mate_in)
        ),
    ),
    "allowed_mate": ("mateIn2", lambda f: bad(f) and f.allowed_mate_in is not None),
    "missed_mate": ("mateIn1", lambda f: bad(f) and f.missed_mate_in is not None),
    "mate_threat_ignored": (
        "middlegame",
        lambda f: bad(f) and f.threat is not None and f.threat.mate_in is not None,
    ),
    "losing_exchange": ("advantage", lambda f: bad(f) and has(f.motifs_against, "losing_exchange")),
    "inaccuracy": ("middlegame", lambda f: f.classification == "inaccuracy"),
    "good_move": ("middlegame", lambda f: f.classification == "good"),
    "best_move": ("opening", lambda f: f.classification == "best" and f.win_chance_drop == 0),
}
PER_KIND = 2  # one item per colour where possible
MAX_PUZZLES = 25


def candidates(fen, moves, rng):
    """(fen, uci) pairs to try: the opponent's own first move, the solution, random moves."""
    first, *rest = moves.split()
    yield fen, first
    b = chess.Board(fen)
    b.push_uci(first)
    if rest:
        yield b.fen(), rest[0]
    legal = [m.uci() for m in b.legal_moves if m.uci() != (rest[0] if rest else "")]
    for uci in rng.sample(legal, min(3, len(legal))):
        yield b.fen(), uci


def main() -> None:
    rng = random.Random(7)
    pool = EnginePool(settings.engines_dir, 1, settings.stockfish_threads, settings.stockfish_hash)
    items = []

    def add(item_id, kind, fen, uci):
        f = build_facts(pool, chess.Board(fen), chess.Move.from_uci(uci), settings)
        items.append(
            {
                "id": item_id,
                "kind": kind,
                "fen": fen,
                "move_uci": uci,
                "facts": json.loads(f.model_dump_json()),
            }
        )
        return f

    try:
        cases = json.loads((ROOT / "backend/tests/fixtures/facts.json").read_text("utf-8"))
        for c in cases:
            if c["id"] in KINDS_OF_CASES:
                add(c["id"], KINDS_OF_CASES[c["id"]], c["fen"], c["move"])
        add("stalemate_black", "stalemate", "7K/8/5k2/8/8/8/8/6q1 b - - 0 1", "g1g6")

        db = sqlite3.connect(settings.puzzles_db_path)
        for kind, (theme, pred) in TARGETS.items():
            rows = db.execute(
                "SELECT p.id, p.fen, p.moves FROM puzzles p JOIN puzzle_themes t ON t.puzzle_id=p.id"
                " WHERE t.theme=? AND p.rating BETWEEN 500 AND 1700 AND p.popularity>=90"
                " ORDER BY random() LIMIT ?",
                (theme, MAX_PUZZLES * 4),
            ).fetchall()
            colours: set[str] = set()
            for pid, fen, moves in rows[:MAX_PUZZLES]:
                if len(colours) >= PER_KIND:
                    break
                for cfen, uci in candidates(fen, moves, rng):
                    f = build_facts(pool, chess.Board(cfen), chess.Move.from_uci(uci), settings)
                    if pred(f) and f.side not in colours:
                        colours.add(f.side)
                        add(f"{kind}_{pid}", kind, cfen, uci)
                        break
            print(f"{kind}: {len(colours)} new", flush=True)
    finally:
        pool.close()

    OUT.write_text(json.dumps(items, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(items)} items -> {OUT}")
    for kind, n in sorted(Counter(i["kind"] for i in items).items()):
        print(f"  {kind}: {n}")
    print("  classes:", dict(Counter(i["facts"]["classification"] for i in items)))


if __name__ == "__main__":
    main()
