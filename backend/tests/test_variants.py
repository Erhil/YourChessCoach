import chess
import pytest

from app.coach.facts import build_facts
from app.coach.variants import (
    analyse_move,
    candidates,
    moves_in_question,
    question_facts,
)
from app.config import settings
from app.engines.pool import EnginePool
from tests.test_validator import facts

# Black has played ...Nf6?? and White has Qxf7#.
FEN1 = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"
FEN2 = "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3"
CASTLE = "r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1"


def raw(fen: str, ucis: list[str], cp: int | None = None, mate: int | None = None) -> dict:
    """An engine line with the score from White's point of view."""
    board = chess.Board(fen)
    san = []
    for uci in ucis:
        move = chess.Move.from_uci(uci)
        san.append(board.san(move))
        board.push(move)
    return {"score": {"cp": cp, "mate": mate}, "pv_san": san, "pv_uci": ucis}


class FakePool:
    """Engine double: `script` maps a FEN to lines (best first); unknown positions are an error."""

    def __init__(self, script: dict[str, list[dict]]):
        self.script = script
        self.calls: list[tuple[str, int]] = []

    def analyse(self, board, depth=None, movetime_ms=None, multipv=1):
        self.calls.append((board.fen(), multipv))
        return depth or 0, self.script[board.fen()][:multipv]


def after_nf6() -> str:
    board = chess.Board(FEN1)
    board.push_uci("g8f6")
    return board.fen()


def after_d6() -> str:
    board = chess.Board(FEN1)
    board.push_uci("d7d6")
    return board.fen()


def script1() -> dict[str, list[dict]]:
    """Position 1: g6 is best, Qe7 is as good, Bc5 and Nf6 lose to Qxf7#."""
    return {
        FEN1: [
            raw(FEN1, ["g7g6", "h5f3", "g8f6", "f3b3"], cp=30),
            raw(FEN1, ["d8e7", "b1c3", "g8f6", "d2d3"], cp=40),
            raw(FEN1, ["f8c5", "h5f7"], mate=1),
            raw(FEN1, ["g8f6", "h5f7"], mate=1),
        ],
        after_nf6(): [raw(after_nf6(), ["h5f7"], mate=1)],
        after_d6(): [raw(after_d6(), ["h5f7"], mate=1)],
    }


def board_pair(fen: str, uci: str) -> tuple[chess.Board, chess.Board]:
    before = chess.Board(fen)
    after = before.copy()
    after.push_uci(uci)
    return before, after


@pytest.mark.parametrize(
    ("fen", "text", "expected"),
    [
        (FEN1, "Что будет после ♕e7?", [("Qe7", "player")]),
        (FEN1, "А что если бы я сыграл d6?", [("d6", "player")]),
        (FEN1, "Почему конь на f6 плохо?", []),
        (FEN1, "Что лучше: ♗c5 или ♘f6?", [("Bc5", "player"), ("Nf6", "player")]),
        (FEN1, "Что если Qe7 или ♕e7?", [("Qe7", "player")]),
        (FEN1, "Почему нельзя Ke8?", []),
        (FEN1, "Что если сходить на d6 слоном?", []),
        (FEN2, "А если белые сыграют ♘g5?", [("Ng5", "opponent")]),
        (CASTLE, "Что если O-O?", [("O-O", "player")]),
        (CASTLE, "А если рокировка 0-0-0?", [("O-O-O", "player")]),
    ],
)
def test_moves_in_question(fen, text, expected):
    before = chess.Board(fen)
    uci = "g8f6" if fen != CASTLE else "a8b8"
    _, after = board_pair(fen, uci)
    found = moves_in_question(text, before, after)
    assert [(n.san, n.owner) for n in found] == expected


def test_moves_in_question_is_limited():
    before, after = board_pair(FEN1, "g8f6")
    found = moves_in_question("d6 g6 Qe7 Bc5", before, after)
    assert len(found) == 3


def test_candidates_verdicts_lines_and_material():
    pool = FakePool(script1())
    cands = candidates(pool, chess.Board(FEN1), 14)
    assert [v.san for v in cands] == ["g6", "Qe7", "Bc5", "Nf6"]
    assert cands[0].verdict == "best" and cands[1].verdict in ("best", "good")
    mated = cands[2]
    assert mated.verdict == "blunder" and mated.mate == -1
    assert [(p.san, p.side) for p in mated.line] == [("Bc5", "black"), ("Qxf7#", "white")]
    assert mated.material.change < 0
    assert cands[0].mover == "black" and cands[0].line[1].side == "white"
    assert all(len(v.line) <= 6 for v in cands)


def test_analyse_move_in_top_lines_and_outside():
    pool = FakePool(script1())
    board = chess.Board(FEN1)
    inside = analyse_move(pool, board, chess.Move.from_uci("f8c5"), 14)
    assert inside.verdict == "blunder" and inside.mate == -1
    outside = analyse_move(pool, board, chess.Move.from_uci("d7d6"), 14)
    assert outside.san == "d6" and outside.mate == -1 and outside.verdict == "blunder"
    assert [(p.san, p.side) for p in outside.line] == [("d6", "black"), ("Qxf7#", "white")]


def test_question_facts_player_and_played_moves():
    pool = FakePool(script1())
    f = facts(
        fen_before=FEN1,
        side="black",
        player_move={"san": "Nf6", "uci": "g8f6"},
        classification="blunder",
        refutation=["Qxf7#"],
        best_line=["g6"],
        best_move={"san": "g6", "uci": "g7g6"},
    )
    q = question_facts(pool, f, "Что лучше: ♗c5 или ♘f6?", settings)
    assert [(a.move.san, a.played) for a in q.asked] == [("Bc5", False), ("Nf6", True)]
    assert q.asked[1].variant.verdict == "blunder"
    bc5 = q.asked[0].variant
    assert bc5.mate == -1 and [(p.san, p.side) for p in bc5.line] == [
        ("Bc5", "black"),
        ("Qxf7#", "white"),
    ]
    assert q.candidates[0].san == "g6"


def test_question_facts_opponent_move_is_analysed_after_the_played_move():
    fen2_after = chess.Board(FEN2)
    fen2_after.push_uci("g8f6")
    after = fen2_after.fen()
    g5 = chess.Board(after)
    g5.push_uci("f3g5")
    script = {
        FEN2: [raw(FEN2, ["g7g6", "d2d3"], cp=20)],
        after: [raw(after, ["d2d3", "d7d5"], cp=30)],
        g5.fen(): [raw(g5.fen(), ["d7d5", "e4d5", "c6a5"], cp=10)],
    }
    f = facts(
        fen_before=FEN2,
        side="black",
        player_move={"san": "Nf6", "uci": "g8f6"},
        classification="good",
    )
    q = question_facts(FakePool(script), f, "А если белые сыграют ♘g5?", settings)
    (asked,) = q.asked
    assert asked.move.owner == "opponent" and asked.variant.mover == "white"
    assert [(p.san, p.side) for p in asked.variant.line][:2] == [("Ng5", "white"), ("d5", "black")]


# Real engine -----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pool():
    p = EnginePool(settings.engines_dir, 1, 2, 64)
    yield p
    p.close()


@pytest.mark.engine
def test_engine_candidates_and_mate_line(pool):
    cands = candidates(pool, chess.Board(FEN1), settings.coach_depth)
    assert len(cands) == 5 and cands[0].verdict == "best"
    qxf7 = analyse_move(pool, chess.Board(FEN1), chess.Move.from_uci("d7d6"), settings.coach_depth)
    assert qxf7.mate == -1 and qxf7.line[1].san == "Qxf7#" and qxf7.line[1].side == "white"
    assert qxf7.verdict == "blunder"


@pytest.mark.engine
def test_engine_opponent_move_has_best_reply(pool):
    f = build_facts(pool, chess.Board(FEN2), chess.Move.from_uci("g8f6"), settings)
    q = question_facts(pool, f, "А если белые сыграют ♘g5?", settings)
    (asked,) = q.asked
    assert asked.move.san == "Ng5" and asked.move.owner == "opponent"
    assert len(asked.variant.line) > 1 and asked.variant.line[1].side == "black"


def test_question_about_the_square_of_the_played_move_is_about_the_played_move():
    f = facts(
        fen_before=FEN1,
        side="black",
        player_move={"san": "Nf6", "uci": "g8f6"},
        classification="blunder",
    )
    q = question_facts(FakePool(script1()), f, "Почему конь на f6 плохо?", settings)
    assert [(a.move.san, a.played) for a in q.asked] == [("Nf6", True)]
    q = question_facts(FakePool(script1()), f, "Что будет после ♕e7?", settings)
    assert [a.move.san for a in q.asked] == ["Qe7"]
