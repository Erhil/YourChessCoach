import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import chess
import pytest

from app.coach import why

CASES = json.loads((Path(__file__).parent / "fixtures" / "why.json").read_text(encoding="utf-8"))


def _id(case):
    return f"{case['kind']}-{'pos' if case['expect'] else 'neg'}-{case['move']}"


def _run(case, board, move, line):
    detector = case["detector"]
    if detector == "removed_defence":
        found = why.removed_defence(board, move, line)
    elif detector == "new_attacks":
        found = why.new_attacks(board, move)
    else:
        found = getattr(why, detector)(board, move)
    return found if isinstance(found, list) else ([found] if found else [])


@pytest.mark.parametrize("case", CASES, ids=[_id(c) for c in CASES])
def test_why_case(case):
    board = chess.Board(case["fen"])
    assert board.is_valid()
    move = chess.Move.from_uci(case["move"])
    assert move in board.legal_moves
    line, b = [], board.copy()
    if case["detector"] == "removed_defence":
        b.push(move)
    for uci in case["line"]:
        line.append(chess.Move.from_uci(uci))
        assert line[-1] in b.legal_moves
        b.push(line[-1])
    found = [r for r in _run(case, board, move, line) if r.kind == case["kind"]]
    assert bool(found) == case["expect"]
    if case["expect"]:
        assert found[0].squares == case["squares"]
        if "detail" in case:
            assert found[0].detail == case["detail"]
        json.dumps(asdict(found[0]))
        assert all(set(p) == {"square", "piece"} for p in found[0].pieces)


def test_case_counts():
    pos = Counter(c["kind"] for c in CASES if c["expect"])
    neg = Counter(c["kind"] for c in CASES if not c["expect"])
    assert len(set(pos) | set(neg)) == 14
    for kind in set(pos) | set(neg):
        assert pos[kind] >= 3 and neg[kind] >= 2, kind


def _board(moves):
    b = chess.Board()
    for san in moves.split():
        b.push_san(san)
    return b


def test_reply_attacks_names_the_most_valuable_piece_first():
    # ...Nd4 trap: after Nxe5 the reply Qg5 hits the e5 knight and the g2 pawn
    b = _board("e4 e5 Nf3 Nc6 Bc4 Nd4")
    b.push_san("Nxe5")
    r = why.new_attacks(b, b.parse_san("Qg5"))
    assert r.squares == ["e5", "g2"]
    assert [p["piece"] for p in r.pieces[1:]] == ["N", "P"]


def test_retreat_of_a_hanging_piece_comes_before_the_attack_idea():
    b = chess.Board(
        "4k3/8/8/3p4/2B5/8/8/4K3 w - - 0 1"
    )  # Bc4 is attacked; Bb5+ retreats with check
    kinds = [(r.kind, r.detail) for r in why.best_move_ideas(b, b.parse_san("Bb5+"))]
    assert kinds[0] == ("best_defends", "retreat")
    assert ("best_attacks", "check") in kinds


def test_pawn_structure_doubled_pawns_after_a_pawn_capture():
    b = chess.Board("4k3/8/8/8/8/2p5/1PP5/1N2K3 w - - 0 1")
    r = why.pawn_structure(b, b.parse_san("bxc3"), b.parse_san("Nxc3"))
    assert r and r.kind == "doubled_pawns" and r.detail == "c" and r.squares == ["c2", "c3"]


def test_pawn_structure_isolated_pawn_is_named():
    # g1.7: bxc3 leaves the pawn a2 alone; the pawns were fine before and after Nxc3
    b = chess.Board("r1bqk1nr/pppp1pbp/2n3p1/8/2B1P3/2p2N2/PP3PPP/RNBQ1RK1 w kq - 0 7")
    r = why.pawn_structure(b, b.parse_san("bxc3"), b.parse_san("Nxc3"))
    assert r and r.kind == "isolated_pawn" and r.squares == ["a2"]


def test_pawn_structure_is_silent_when_the_best_move_makes_the_same():
    b = chess.Board("4k3/8/8/8/8/2p5/1PPP4/4K3 w - - 0 1")  # bxc3 and dxc3 both double the c-file
    assert why.pawn_structure(b, b.parse_san("bxc3"), b.parse_san("dxc3")) is None


def test_pawn_structure_is_silent_when_the_move_keeps_the_structure():
    b = chess.Board("4k3/8/8/8/8/2p5/1PPP4/1N2K3 w - - 0 1")
    assert why.pawn_structure(b, b.parse_san("Nxc3"), b.parse_san("bxc3")) is None


# White Be2 is boxed in by the pawns d3 and f3 (it attacks 4 squares); Qd2 attacks 15.
PASSIVE_FEN = "r1bqkbnr/pppp1ppp/2n5/4p3/8/3P1P2/PPP3PP/RNBQKB1R w KQkq - 0 4"


def test_passive_piece_bishop_in_a_box_against_an_open_best_move():
    b = chess.Board(PASSIVE_FEN)
    r = why.passive_piece(b, b.parse_san("Be2"), b.parse_san("Qd2"))
    assert r and r.kind == "passive_piece" and r.squares == ["e2"] and r.detail == "4"
    assert r.pieces == [{"square": "e2", "piece": "B"}]


def test_passive_piece_is_silent_when_the_gap_is_small():
    b = chess.Board(PASSIVE_FEN)
    assert why.passive_piece(b, b.parse_san("Be2"), b.parse_san("Na3")) is None  # 4 and 4


def test_passive_piece_is_silent_for_a_knight_move():
    b = chess.Board(PASSIVE_FEN)
    assert why.passive_piece(b, b.parse_san("Na3"), b.parse_san("Qd2")) is None


def test_passive_piece_is_silent_when_the_best_move_is_a_king_or_pawn_move():
    b = chess.Board(PASSIVE_FEN)
    assert why.passive_piece(b, b.parse_san("Be2"), b.parse_san("Kd2")) is None
    assert why.passive_piece(b, b.parse_san("Be2"), b.parse_san("g3")) is None


def test_passive_piece_is_silent_when_the_moved_piece_attacks_many_squares():
    b = chess.Board("4k3/8/8/8/8/8/8/2B1K1N1 w - - 0 1")
    assert why.passive_piece(b, b.parse_san("Bg5"), b.parse_san("Nf3")) is None


def test_passive_piece_counts_a_rook_boxed_in_by_its_own_pieces():
    b = chess.Board("4k3/8/8/8/8/5N2/5PP1/4K2R w - - 0 1")
    r = why.passive_piece(b, b.parse_san("Rg1"), b.parse_san("Ne5"))
    assert r and r.squares == ["g1"] and r.detail == "4" and r.pieces[0]["piece"] == "R"
