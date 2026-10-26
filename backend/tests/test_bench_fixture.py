import json
from pathlib import Path

import chess

from app.coach.schema import CoachFacts

ITEMS = json.loads((Path(__file__).parent / "fixtures" / "bench.json").read_text(encoding="utf-8"))


def test_bench_size_and_ids():
    assert len(ITEMS) >= 25
    assert len({i["id"] for i in ITEMS}) == len(ITEMS)


def test_bench_items_parse_and_move_is_legal():
    for item in ITEMS:
        facts = CoachFacts.model_validate(item["facts"])
        board = chess.Board(item["fen"])
        assert chess.Move.from_uci(item["move_uci"]) in board.legal_moves, item["id"]
        assert facts.player_move.uci == item["move_uci"], item["id"]
        assert facts.fen_before == board.fen(), item["id"]


def test_bench_covers_all_classifications_and_both_colours():
    facts = [CoachFacts.model_validate(i["facts"]) for i in ITEMS]
    assert {f.classification for f in facts} == {"best", "good", "inaccuracy", "mistake", "blunder"}
    assert {f.side for f in facts} == {"white", "black"}
