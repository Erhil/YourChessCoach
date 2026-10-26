import chess
import pytest
from fastapi.testclient import TestClient

from app.coach.hint import build_hint
from app.config import settings
from app.main import create_app

# White to move; Black threatens Qh4#.
MATE_THREAT = "rnbqkbnr/pppp1ppp/8/4p3/6P1/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3"
CP = {"cp": 20, "mate": None}


class FakePool:
    """Answers the first call (own best move) and the second call (null move) from a script."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = 0

    def analyse(self, board, depth=None, movetime_ms=None, multipv=1):
        self.calls += 1
        san, uci, score, *more = self.answers.pop(0)
        tail_san, tail_uci = more or ([], [])
        line = {"rank": 1, "score": score, "pv_san": [san, *tail_san], "pv_uci": [uci, *tail_uci]}
        return depth, [line]


def test_threat_mate_and_best_piece():
    pool = FakePool(("e4", "e2e4", CP), ("Qh4#", "d8h4", {"cp": None, "mate": -1}))
    h = build_hint(pool, chess.Board(MATE_THREAT), 8)
    assert h["threat"] == {"san": "Qh4#", "uci": "d8h4", "wins": None, "mate": True}
    assert h["best"] == {"san": "e4", "uci": "e2e4", "piece": "P"}


def test_threat_names_the_piece_it_wins():
    # Black to move after the null move takes the knight on e5.
    board = chess.Board("4r1k1/8/8/4N3/8/8/8/4K3 w - - 0 1")
    # The line goes on to a quiet Kd2: a PV that ends after a capture claims no material.
    reply = ("Rxe5+", "e8e5", {"cp": -300, "mate": None}, ["Kd2"], ["e1d2"])
    pool = FakePool(("Nd7", "e5d7", CP), reply)
    h = build_hint(pool, board, 8)
    assert h["threat"] == {"san": "Rxe5+", "uci": "e8e5", "wins": "коня", "mate": False}


def test_quiet_reply_is_not_a_threat():
    pool = FakePool(("Nc3", "b1c3", CP), ("Nf6", "g8f6", CP))
    h = build_hint(pool, chess.Board(MATE_THREAT), 8)
    assert h["threat"] is None
    assert h["best"] == {"san": "Nc3", "uci": "b1c3", "piece": "N"}


def test_no_null_move_search_in_check():
    check = "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3"
    pool = FakePool(("g3", "g4g3", CP))
    assert chess.Board(check).is_check()
    assert build_hint(pool, chess.Board(check), 8)["threat"] is None
    assert pool.calls == 1


@pytest.fixture
def client():
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.mark.engine
def test_route_with_engine(client):
    r = client.post("/api/coach/hint", json={"fen": MATE_THREAT})
    assert r.status_code == 200
    body = r.json()
    assert body["threat"]["uci"] == "d8h4"
    assert body["best"]["piece"] in "PNBRQK"


@pytest.mark.parametrize("fen", ["nonsense", "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"])
def test_route_invalid_is_422(client, fen):
    assert client.post("/api/coach/hint", json={"fen": fen}).status_code == 422
