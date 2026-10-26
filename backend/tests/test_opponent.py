import chess
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.engines.opponent import LEVELS, Opponent
from app.main import create_app

MIDDLEGAME = "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"
MIDDLEGAME_MOVES = ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "g8f6"]
MATE_MOVES = ["f2f3", "e7e5", "g2g4", "d8h4"]  # fool's mate: the game is over


def board_after(moves):
    board = chess.Board()
    for uci in moves:
        board.push_uci(uci)
    return board


@pytest.fixture
def client():
    with TestClient(create_app(settings)) as c:  # exit closes the opponent engines
        yield c


@pytest.fixture
def fallback():
    opponent = Opponent(settings.engines_dir, use_maia=False)
    yield opponent
    opponent.close()


def test_levels_lists_six(client):
    data = client.get("/api/opponent/levels").json()
    assert [d["level"] for d in data] == list(LEVELS)
    assert data[0]["label"] == "Новичок (800)"
    assert {d["engine"] for d in data} <= {"maia", "stockfish"}


@pytest.mark.parametrize(
    "body",
    [
        {"moves": ["e2e5"], "level": 1100},
        {"moves": [], "level": 1000},
        {"moves": MATE_MOVES, "level": 1100},
        {"level": 1100},
    ],
)
def test_invalid_request_is_422(client, body):
    assert client.post("/api/opponent/move", json=body).status_code == 422


@pytest.mark.engine
@pytest.mark.parametrize("level", list(LEVELS))
@pytest.mark.parametrize("moves", [[], MIDDLEGAME_MOVES])
def test_every_level_returns_legal_move(client, level, moves):
    response = client.post("/api/opponent/move", json={"moves": moves, "level": level})
    assert response.status_code == 200
    body = response.json()
    assert chess.Move.from_uci(body["uci"]) in board_after(moves).legal_moves
    assert body["engine"] in ("maia", "stockfish")


@pytest.mark.engine
@pytest.mark.parametrize("level", list(LEVELS))
def test_fallback_returns_legal_move(fallback, level):
    board = chess.Board(MIDDLEGAME)
    move, engine = fallback.move(board, level)
    assert engine == "stockfish"
    assert move in board.legal_moves


@pytest.mark.engine
def test_lc0_start_failure_falls_back_to_stockfish(tmp_path):
    opponent = Opponent(settings.engines_dir)
    if opponent.engine_name(1100) != "maia":
        pytest.skip("no lc0 with Maia weights")
    opponent._lc0 = tmp_path / "missing-lc0"  # the process cannot start
    try:
        move, engine = opponent.move(chess.Board(MIDDLEGAME), 1100)
        assert engine == "stockfish"
        assert move in chess.Board(MIDDLEGAME).legal_moves
        assert opponent.engine_name(1100) == "stockfish"
    finally:
        opponent.close()
