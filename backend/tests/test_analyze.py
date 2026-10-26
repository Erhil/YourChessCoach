import chess
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import create_app

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
WHITE_MATES = "6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1"  # Ra8#
BLACK_MATES = "r5k1/8/8/8/8/8/5PPP/6K1 b - - 0 1"  # Ra1#
CHECKMATED = "R5k1/5ppp/8/8/8/8/8/6K1 b - - 0 1"


@pytest.fixture
def client():
    with TestClient(create_app(settings)) as c:  # exit closes the engine pool
        yield c


def analyze(client, **body):
    return client.post("/api/analyze", json=body)


@pytest.mark.parametrize(
    "body",
    [
        {"fen": "not a fen"},
        {"fen": "8/8/8/8/8/8/8/8 w - - 0 1"},
        {"fen": START, "depth": 0},
        {"fen": START, "depth": 31},
        {"fen": START, "depth": 21},  # cap is 20
        {"fen": START, "movetime_ms": 3001},  # cap is 3000
        {"fen": START + " " * 100},
        {"fen": START, "movetime_ms": 5},
        {"fen": START, "multipv": 6},
    ],
)
def test_invalid_request_is_422(client, body):
    assert analyze(client, **body).status_code == 422


@pytest.mark.engine
def test_start_position(client):
    r = analyze(client, fen=START, depth=8)
    assert r.status_code == 200
    body = r.json()
    assert body["turn"] == "white"
    assert len(body["lines"]) == 1
    line = body["lines"][0]
    assert line["rank"] == 1
    assert chess.Move.from_uci(line["pv_uci"][0]) in chess.Board(START).legal_moves
    assert len(line["pv_san"]) == len(line["pv_uci"])


@pytest.mark.engine
def test_mate_in_1_for_white(client):
    line = analyze(client, fen=WHITE_MATES, depth=8).json()["lines"][0]
    assert line["score"] == {"cp": None, "mate": 1}


@pytest.mark.engine
def test_mate_in_1_for_black(client):
    body = analyze(client, fen=BLACK_MATES, depth=8).json()
    assert body["turn"] == "black"
    assert body["lines"][0]["score"]["mate"] == -1


@pytest.mark.engine
def test_multipv(client):
    lines = analyze(client, fen=START, depth=8, multipv=3).json()["lines"]
    assert [x["rank"] for x in lines] == [1, 2, 3]
    assert len({x["pv_uci"][0] for x in lines}) == 3


@pytest.mark.engine
def test_checkmated_position(client):
    assert analyze(client, fen=CHECKMATED).json()["lines"] == []


@pytest.mark.engine
def test_default_movetime(client):
    assert analyze(client, fen=START).json()["lines"]
