from pathlib import Path

import chess
import pytest

from app.coach.classify import win_chance
from app.config import settings
from app.engines.pool import EnginePool
from app.lessons.loader import list_lessons

LESSONS = list_lessons(settings.lessons_dir)
FIXTURE_LESSONS = list_lessons(Path(__file__).parent / "fixtures" / "lessons")
LINE_CASES = [
    pytest.param(x, seg, id=f"{x['slug']}#{n}")
    for x in LESSONS + FIXTURE_LESSONS
    for n, seg in enumerate((s for s in x["segments"] if s["type"] == "line"), start=1)
]
SLUGS = {x["slug"] for x in LESSONS}
CASES = [
    pytest.param(x, seg, id=f"{x['slug']}#{n}")
    for x in LESSONS
    for n, seg in enumerate((s for s in x["segments"] if s["type"] == "chess"), start=1)
]


@pytest.mark.parametrize("lesson", LESSONS, ids=lambda x: x["slug"])
def test_front_matter(lesson):
    assert lesson["title"]
    assert lesson["level"] in (1, 2, 3)
    assert lesson["themes"]
    assert set(lesson["prerequisites"]) <= SLUGS


@pytest.mark.parametrize(("lesson", "seg"), CASES)
def test_position_is_legal(lesson, seg):
    board = chess.Board(seg["fen"])
    assert board.is_valid(), f"illegal FEN {seg['fen']}"
    for san in seg["solution"]:
        try:
            board.push_san(san)  # a move is legal for the side to move or it raises
        except ValueError as e:
            pytest.fail(f"solution move {san} is not legal: {e}")


@pytest.fixture(scope="module")
def pool():
    p = EnginePool(settings.engines_dir, 1, settings.stockfish_threads, settings.stockfish_hash)
    yield p
    p.close()


@pytest.mark.engine
@pytest.mark.parametrize(("lesson", "seg"), CASES)
def test_first_move_is_best(lesson, seg, pool):
    """The first solution move must be best, or equal to the best.

    Rule: after the move the board is checkmate, or Stockfish (depth 18) sees a forced mate
    for the mover, or the move scores at most 30 centipawns below the best move, or both win
    clearly (+3 pawns or more) and the app would not call the move an inaccuracy
    (search noise at +6 is wider than 30 cp: +555 vs +626 for the same tactic).
    The start position is searched once with multipv 5. If the move is one of these 5 lines,
    its score is compared with the top line of the same search, so search noise between two
    separate searches does not matter. If the move is not among the 5 lines, the position
    after the move is searched separately and its score is compared with the top line.
    All scores are taken for the mover.
    """
    board = chess.Board(seg["fen"])
    mover = board.turn
    sign = 1 if mover == chess.WHITE else -1
    san = seg["solution"][0]
    move = board.parse_san(san)

    def mover_cp(line):
        score = line["score"]
        if score["mate"] is not None:
            value = sign * score["mate"]
            return (100000 if value > 0 else -100000), True
        return sign * score["cp"], False

    _, lines = pool.analyse(board, depth=18, multipv=5)
    best_cp, _ = mover_cp(lines[0])
    best_san = lines[0]["pv_san"][0]
    same_search = next((x for x in lines if x["pv_uci"] and x["pv_uci"][0] == move.uci()), None)

    if same_search is not None:
        cp, is_mate = mover_cp(same_search)
        if is_mate and cp > 0:
            return  # forced mate for the mover
    else:
        board.push(move)
        if board.is_checkmate():
            return
        _, after = pool.analyse(board, depth=18)
        cp, is_mate = mover_cp(after[0])
        if is_mate and cp > 0:
            return  # forced mate for the mover
    drop = win_chance(best_cp) - win_chance(cp)
    decisive = cp >= 300 and drop < settings.coach_inaccuracy
    assert cp >= best_cp - 30 or decisive, (
        f"{san} scores {cp} for the mover; best is {best_san} with {best_cp}"
    )


def _student_cp(line, student):
    score = line["score"]
    value = score["mate"] * 100000 if score["mate"] is not None else score["cp"]
    return value if student == chess.WHITE else -value


def _replay(seg):
    """Yield (board before the move, move, move item) for each move of a line block."""
    board = chess.Board(seg["fen"])
    assert board.is_valid(), f"illegal FEN {seg['fen']}"
    for item in seg["moves"]:
        assert item["text"].strip(), f"{item['san']} has no text"
        try:
            move = board.parse_san(item["san"])
        except ValueError as e:
            pytest.fail(f"line move {item['san']} is not legal: {e}")
        yield board.copy(), move, item
        board.push(move)


@pytest.mark.parametrize(("lesson", "seg"), LINE_CASES)
def test_line_is_legal(lesson, seg):
    assert seg["title"]
    assert list(_replay(seg))


@pytest.mark.engine
@pytest.mark.parametrize(("lesson", "seg"), LINE_CASES)
def test_line_student_moves_are_near_best(lesson, seg, pool):
    """Each move of the student's side scores at most 50 centipawns below the best move.

    One multipv 5 search (depth 18) per position, as in the chess-block check. A move outside
    the 5 lines is scored by a search of the position after it: in the opening many moves are
    almost equal, and a good move can be sixth. The other side's moves are not checked.
    """
    student = chess.WHITE if seg["side"] == "white" else chess.BLACK
    for board, move, item in _replay(seg):
        if board.turn != student:
            continue
        _, lines = pool.analyse(board, depth=18, multipv=5)
        found = next((x for x in lines if x["pv_uci"] and x["pv_uci"][0] == move.uci()), None)
        if found is None:
            after = board.copy()
            after.push(move)
            found = pool.analyse(after, depth=18)[1][0]  # scores are from White's view
        assert _student_cp(found, student) >= _student_cp(lines[0], student) - 50, (
            f"{item['san']} scores {_student_cp(found, student)}; best is {_student_cp(lines[0], student)}"
        )
