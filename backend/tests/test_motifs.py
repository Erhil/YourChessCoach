import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import chess
import pytest

from app.coach import motifs

CASES = json.loads((Path(__file__).parent / "fixtures" / "motifs.json").read_text(encoding="utf-8"))
COLOR_BASED = ("hanging_pieces",)


def _id(case):
    return f"{case['detector']}-{'pos' if case['expect'] else 'neg'}-{case['fen'].split()[0][:20]}"


@pytest.mark.parametrize("case", CASES, ids=[_id(c) for c in CASES])
def test_motif_case(case):
    board = chess.Board(case["fen"])
    assert board.is_valid()
    if case["detector"] in COLOR_BASED:
        arg = chess.WHITE if case["color"] == "white" else chess.BLACK
    else:
        arg = chess.Move.from_uci(case["move"])
        assert arg in board.legal_moves
    result = getattr(motifs, case["detector"])(board, arg)
    found = result if isinstance(result, list) else ([result] if result else [])
    assert bool(found) == case["expect"]
    json.dumps([asdict(m) for m in found])
    if not case["expect"]:
        return
    assert {t["square"] for m in found for t in m.targets} == set(case["targets"])
    if "san" in case:
        assert [m.move_san for m in found] == [case["san"]]
    if "material" in case:
        assert found[0].material == case["material"]


def test_case_counts():
    pos = Counter(c["detector"] for c in CASES if c["expect"])
    neg = Counter(c["detector"] for c in CASES if not c["expect"])
    names = {c["detector"] for c in CASES}
    assert len(names) == 7
    for name in names:
        assert pos[name] >= 3 and neg[name] >= 2, name


def test_pin_needs_a_more_valuable_piece_behind():
    # Italian, 4.Ng5?? Qxg5: the queen "pins" the d2 pawn to the c1 bishop, but Qxc1 loses the queen
    b = chess.Board("r1bqk1nr/pppp1ppp/2n5/2b1p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4")
    b.push_san("Ng5")
    assert motifs.pin(b, b.parse_san("Qxg5")) is None


def test_pin_to_the_king_is_still_a_pin():
    b = chess.Board("4k3/8/2n5/8/8/8/4B3/4K3 w - - 0 1")
    found = motifs.pin(b, b.parse_san("Bb5"))
    assert found and [t["square"] for t in found.targets] == ["c6", "e8"]


def test_queen_pins_a_knight_to_an_undefended_rook():
    # The rook d8 is worth less than the queen, but nothing guards it: a real pin
    b = chess.Board("3r2k1/3n1ppp/8/8/8/8/8/1Q2K3 w - - 0 1")
    found = motifs.pin(b, b.parse_san("Qd3"))
    assert found and [t["square"] for t in found.targets] == ["d7", "d8"]


def test_queen_does_not_pin_a_knight_to_a_guarded_rook():
    b = chess.Board("3rk3/3n1ppp/8/8/8/8/8/1Q2K3 w - - 0 1")  # the king e8 guards the rook
    assert motifs.pin(b, b.parse_san("Qd3")) is None
