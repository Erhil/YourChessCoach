import dataclasses

import chess
import pytest
from fastapi.testclient import TestClient

from app.coach import ask
from app.coach.facts import build_facts
from app.coach.templates import fig
from app.coach.variants import question_facts
from app.config import settings
from app.db import connect, migrate
from app.engines.pool import EnginePool
from app.main import create_app
from tests.test_validator import facts
from tests.test_variants import FakePool, raw, script1

HUNG_QUEEN = "rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2"
ON = dataclasses.replace(settings, llm_enabled=True)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "t.db"
    migrate(path)
    conn = connect(path)
    yield conn
    conn.close()


def test_why_names_loss_and_motif():
    text = ask.why(facts())
    assert "♘xh4" in text and "ферзя" in text and "под боем" in text


def test_threat_names_reply():
    text = ask.threat(facts())
    assert text.startswith("Соперник может ответить ♘xh4.")
    assert "под боем" in text


def test_better_names_best_move_and_line():
    text = ask.better(facts())
    assert "♘c6" in text and "♗b5" in text


def test_better_says_what_is_given_back():
    f = facts(missed_material={"change": 6, "lost": ["N"], "gained": ["Q"]})
    assert "Он выигрывает ферзя за коня" in ask.better(f)


def test_why_starts_with_the_missed_win_when_the_reply_is_a_quiet_defence():
    f = facts(
        classification="mistake",
        material={"change": 0, "lost": [], "gained": []},
        refutation=["Kf2"],
        motifs_against=[],
        missed_material={"change": 9, "lost": [], "gained": ["Q"]},
    )
    text = ask.why(f)
    assert text.startswith("Можно было выиграть ферзя: ♘c6.") and "Kf2" not in text
    # the player loses material: the reply stays first
    g = facts(
        classification="mistake",
        material={"change": -3, "lost": ["N"], "gained": []},
        refutation=["Kf2"],
        motifs_against=[],
        missed_material={"change": 9, "lost": [], "gained": ["Q"]},
    )
    assert ask.why(g).startswith("После ♕h4 соперник может ответить")


def test_verdict_sentence_names_its_move():
    q = question_facts_for_verdict()
    text = ask._player_move(q)
    assert "♕e7 — " in text and "Это " not in text


def test_better_when_played_move_is_best():
    f = facts(classification="best", best_move={"san": "Qh4", "uci": "d8h4"})
    assert "и есть лучший" in ask.better(f)


def test_good_move_is_not_blamed():
    assert ask.why(facts(classification="good")) == ask.FINE


def test_no_refutation_no_threat():
    assert ask.threat(facts(refutation=[])) == ask.NO_THREAT


def test_mate_threat():
    assert "мат в 1" in ask.threat(facts(allowed_mate_in=1, refutation=["Qh4#"]))


def test_line():
    f = facts(best_line=["Nc6", "Bb5", "Nf6", "O-O"], refutation=["Nxh4", "Nc6", "Bb5"])
    better = ask.line(f, "better")
    assert better == {"fen": f.fen_before, "moves": ["Nc6", "Bb5", "Nf6"]}
    for question in ("why", "threat"):
        out = ask.line(f, question)
        assert out["moves"] == ["Nxh4"]
        board = chess.Board(out["fen"])
        assert board.turn == chess.WHITE and board.parse_san(
            "Nxh4"
        )  # the base is the position after the move


def test_free_without_pool_is_the_grounded_template(db):
    out = ask.answer(facts(), "free", "Почему?", settings)
    assert out["source"] == "template" and out["reason"] is None
    assert out["answer"].startswith(ask.why(facts()))
    assert ask.better(facts()) in out["answer"]


def test_free_is_the_template_when_the_llm_is_on():
    f = blunder_facts()
    out = ask.answer(f, "free", "Что если Bc5?", ON, FakePool(script1()))
    q = question_facts(FakePool(script1()), f, "Что если Bc5?", ON)
    assert out["source"] == "template" and out["answer"] == ask.grounded(f, q)


def test_endpoint_input():
    with TestClient(create_app(ON)) as c:
        base = {"fen": HUNG_QUEEN, "move": "d8h4"}
        assert c.post("/api/coach/ask", json=base | {"question": "free"}).status_code == 422
        assert c.post("/api/coach/ask", json=base | {"question": "x"}).status_code == 422
        long = {"question": "free", "text": "а" * 301}
        assert c.post("/api/coach/ask", json=base | long).status_code == 422
        assert (
            c.post("/api/coach/ask", json={**base, "move": "a1a8", "question": "why"}).status_code
            == 422
        )


@pytest.fixture(scope="module")
def pool():
    p = EnginePool(settings.engines_dir, 1, 2, 64)
    yield p
    p.close()


@pytest.mark.engine
def test_hung_queen_with_engine(pool):
    f = build_facts(pool, chess.Board(HUNG_QUEEN), chess.Move.from_uci("d8h4"), settings)
    assert "ферзя" in ask.why(f) and "♘xh4" in ask.why(f)
    assert "♘xh4" in ask.threat(f)
    assert fig(f.best_move.san) in ask.better(f)
    out = ask.line(f, "threat")
    assert chess.Board(out["fen"]).parse_san(out["moves"][0]).to_square == chess.H4


@pytest.mark.engine
def test_endpoint_with_engine():
    with TestClient(create_app(settings)) as c:
        body = {"fen": HUNG_QUEEN, "move": "d8h4"}
        out = c.post("/api/coach/ask", json=body | {"question": "threat"}).json()
        assert out["source"] == "template" and "♘xh4" in out["answer"] and out["line"]["moves"]
        out = c.post("/api/coach/ask", json=body | {"question": "free", "text": "Почему?"}).json()
        assert out["source"] == "template" and out["answer"] and out["reason"] is None


# Free questions with moves ---------------------------------------------------------------

FEN1 = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"
FEN2 = "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3"


def blunder_facts():
    return facts(
        fen_before=FEN1,
        side="black",
        player_move={"san": "Nf6", "uci": "g8f6"},
        classification="blunder",
        refutation=["Qxf7#"],
        best_move={"san": "g6", "uci": "g7g6"},
        best_line=["g6", "Qf3"],
        allowed_mate_in=1,
    )


def test_template_answer_names_mate_and_better_move(db):
    pool = FakePool(script1())
    out = ask.answer(blunder_facts(), "free", "Что если Bc5?", settings, pool)
    assert out["source"] == "template" and out["reason"] is None
    assert "♗c5" in out["answer"] and "♕xf7# — это мат" in out["answer"]
    assert "Лучше было g6." in out["answer"]


def test_template_answer_compares_two_moves(db):
    pool = FakePool(script1())
    out = ask.answer(blunder_facts(), "free", "Что лучше: Qe7 или Bc5?", settings, pool)
    text = out["answer"]
    assert "♕e7" in text and "♗c5" in text and "Из этих ходов лучше ♕e7." in text


def test_template_answer_about_the_played_move_and_a_good_alternative(db):
    pool = FakePool(script1())
    out = ask.answer(blunder_facts(), "free", "Что лучше: Qe7 или Nf6?", settings, pool)
    assert "После вашего хода ♘f6 соперник может ответить ♕xf7# — это мат." in out["answer"]
    assert "лучше ♕e7" in out["answer"]


def test_template_answer_for_an_opponent_move(db):
    after = chess.Board(FEN2)
    after.push_uci("g8f6")
    g5 = after.copy()
    g5.push_uci("f3g5")
    script = {
        FEN2: [raw(FEN2, ["g7g6", "d2d3"], cp=20)],
        after.fen(): [raw(after.fen(), ["d2d3", "d7d5"], cp=30)],
        g5.fen(): [raw(g5.fen(), ["d7d5", "e4d5", "c6a5"], cp=10)],
    }
    f = facts(
        fen_before=FEN2,
        side="black",
        player_move={"san": "Nf6", "uci": "g8f6"},
        classification="good",
    )
    out = ask.answer(f, "free", "А если белые сыграют ♘g5?", settings, FakePool(script))
    assert out["answer"].startswith("Если соперник сыграет ♘g5, лучший ответ — d5.")


def test_question_without_moves_is_the_why_and_better_answer(db):
    f = blunder_facts()
    out = ask.answer(f, "free", "Почему?", settings, FakePool(script1()))
    assert out["source"] == "template" and out["reason"] is None
    assert out["answer"].startswith(ask.why(f)) and "Лучше было g6." in out["answer"]
    assert ask.threat(f) not in out["answer"]  # no threat left unanswered in the facts


def test_better_names_other_good_moves(db):
    f = blunder_facts()
    plain = ask.answer(f, "better", None, settings)["answer"]
    assert "Почти так же" not in plain
    full = ask.answer(f, "better", None, settings, FakePool(script1()))["answer"]
    assert full.endswith("Почти так же хорош ♕e7.")


# Real engine -----------------------------------------------------------------------------


@pytest.mark.engine
def test_engine_questions_name_their_moves(pool, db):
    f = build_facts(pool, chess.Board(FEN1), chess.Move.from_uci("g8f6"), settings)
    out = ask.answer(f, "free", "Что будет после ♕e7?", settings, pool)
    assert out["source"] == "template" and "♕e7" in out["answer"]
    out = ask.answer(f, "free", "А что если бы я сыграл d6?", settings, pool)
    assert "♕xf7# — это мат" in out["answer"] and "d6" in out["answer"]
    out = ask.answer(f, "free", "Что лучше: ♗c5 или ♘f6?", settings, pool)
    assert "♗c5" in out["answer"] and "♘f6" in out["answer"]


@pytest.mark.engine
def test_engine_opponent_move_answer(pool, db):
    f = build_facts(pool, chess.Board(FEN2), chess.Move.from_uci("g8f6"), settings)
    out = ask.answer(f, "free", "А если белые сыграют ♘g5?", settings, pool)
    assert out["answer"].startswith("Если соперник сыграет ♘g5, лучший ответ — ")
    q = question_facts(pool, f, "♘g5", settings)
    best_reply = fig(q.asked[0].variant.line[1].san)
    assert best_reply in out["answer"]


@pytest.mark.engine
def test_engine_better_names_other_good_moves(pool, db):
    f = build_facts(pool, chess.Board(FEN1), chess.Move.from_uci("g8f6"), settings)
    text = ask.answer(f, "better", None, settings, pool)["answer"]
    assert "Почти так же" in text


# Review blockers (Stockfish depth 20 checks) ---------------------------------------------


def elephant_trap() -> chess.Board:
    board = chess.Board()
    for san in ["d4", "d5", "c4", "e6", "Nc3", "Nf6", "Bg5", "Nbd7", "cxd5", "exd5"]:
        board.push_san(san)
    return board


@pytest.mark.engine
def test_engine_why_does_not_blame_the_reply_piece_for_a_discovered_attack(pool, db):
    board = elephant_trap()
    f = build_facts(pool, board, board.parse_san("Nxd5"), settings)
    text = ask.why(f)
    assert "конь соперника нападёт на вашего слона на g5" not in text
    free = ask.answer(f, "free", "Почему этот ход плохой?", settings, pool)
    assert free["source"] == "template" and free["answer"] and free["reason"] is None
    assert "конь соперника нападёт на вашего слона на g5" not in free["answer"]


@pytest.mark.engine
def test_engine_mate_reply_is_not_called_a_check(pool):
    f = build_facts(pool, chess.Board(FEN1), chess.Move.from_uci("g8f6"), settings)
    text = ask.why(f)
    assert "мат в 1" in text and "объявит шах" not in text


@pytest.mark.engine
def test_engine_opponent_capture_is_counted_along_the_whole_exchange(pool, db):
    board = elephant_trap()
    f = build_facts(pool, board, board.parse_san("Nxd5"), settings)
    q = question_facts(pool, f, "А если соперник сыграет Nxd5?", settings)
    (asked,) = q.asked
    assert asked.move.owner == "opponent" and asked.variant.material.change >= 0
    out = ask.answer(f, "free", "А если соперник сыграет Nxd5?", settings, pool)
    assert "теряет ферзя" not in out["answer"] and "♘xd5" in out["answer"]


def question_facts_for_verdict():
    from app.coach.schema import Material
    from app.coach.variants import Asked, NamedMove, Ply, Variant

    v = Variant(
        san="Qe7",
        uci="d8e7",
        mover="black",
        verdict="best",
        win_chance=0.5,
        mate=None,
        line=[Ply(san="Qe7", side="black"), Ply(san="Nc3", side="white")],
        material=Material(change=0, lost=[], gained=[]),
    )
    return Asked(NamedMove("Qe7", "d8e7", "player"), v)
