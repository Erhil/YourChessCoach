import chess
import pytest
from fastapi.testclient import TestClient

from app.main import create_app

MATE = "1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7#"
LONG = (
    "1. e4 d6 2. Nf3 g6 3. Nc3 Bg7 4. Bc4 c6 5. d4 b5 6. Bd3 Nf6 7. h3 Bb7 8. e5 dxe5 "
    "9. dxe5 Ng8 10. Bf4 Bh6 11. Bxh6 Qxd3 12. cxd3 c5 13. Bg7 Nd7 14. e6 Ba6 15. Bxh8 O-O-O "
    "16. Ng1 fxe6 17. b4 c4 18. dxc4 bxc4 19. Qf3 Ngf6 20. h4 Bb7 21. Qh3 Nh5 22. Nce2 Rg8 "
    "23. Bd4 Rd8 24. Bxa7 Bd5 25. Be3 Ne5 26. a4 Rg8 27. Bg5 Kb7 28. Rd1 Rb8 29. Qc3 h6 "
    "30. Bxe7 Ng4 31. Qd4 c3 32. Nxc3 Ra8 33. Qxg4 Rf8 34. Rxd5 Rf5 35. Rc5 Rxc5 36. Qxe6 Rxc3 "
    "37. Qd5+ Rc6 38. b5 Ka7 39. Bc5+ Kb8 40. Qd8+ Kb7"
)


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app()) as c:
        yield c


def test_bad_pgn_is_422(client):
    assert client.post("/api/review", json={"pgn": "not a pgn"}).status_code == 422
    assert client.post("/api/review", json={"pgn": "1. e4 e5 2. Ke5"}).status_code == 422
    assert client.post("/api/review", json={}).status_code == 422


def test_unknown_game_is_404(client):
    assert client.post("/api/review", json={"game_id": 999999}).status_code == 404


@pytest.mark.engine
def test_blunder_and_mate(client):
    r = client.post("/api/review", json={"pgn": MATE, "side": "black"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["side"] == "black" and len(data["moves"]) == 7
    assert data["moves"][-1]["eval_after"]["mate"] == 0
    assert data["moves"][5]["san"] == "Nf6" and data["moves"][5]["classification"] == "blunder"
    assert data["summary"]["blunder"] >= 1
    moment = next(m for m in data["key_moments"] if m["san"] == "Nf6")
    assert moment["explanation"]["text"] and moment["explanation"]["source"] == "template"


@pytest.mark.engine
def test_game_id(client):
    gid = client.post(
        "/api/games", json={"pgn": MATE, "player_color": "black", "result": "1-0"}
    ).json()["id"]
    data = client.post("/api/review", json={"game_id": gid}).json()
    assert data["side"] == "black" and len(data["moves"]) == 7


@pytest.mark.engine
def test_long_game_key_moments(client):
    data = client.post("/api/review", json={"pgn": LONG, "side": "black"}).json()
    assert len(data["moves"]) == 80 and 3 <= len(data["key_moments"]) <= 5


def test_key_moments_drop_candidates_that_facts_call_good(monkeypatch):
    from app.review import routes

    def move(i, drop):
        return {
            "ply": i,
            "san": f"m{i}",
            "uci": "e2e4",
            "color": "white",
            "fen_before": chess.STARTING_FEN,
            "eval_after": {"cp": 0, "mate": None},
            "classification": "mistake",
            "drop": drop,
        }

    class _Facts(dict):
        classification = property(lambda self: self["classification"])

    rows = [move(i, 1.0 - i / 10) for i in range(1, 6)]
    monkeypatch.setattr(routes, "review_moves", lambda *a: [dict(r) for r in rows])
    monkeypatch.setattr(
        routes, "explain_facts", lambda *a: {"text": "text", "source": "template", "model": None}
    )

    def fake_facts(pool, board, mv, settings):
        return _Facts(classification=_CLS.pop(0))

    _CLS = ["good", "blunder", "mistake", "inaccuracy", "mistake"]
    monkeypatch.setattr(routes, "build_facts", fake_facts)
    with TestClient(create_app()) as c:
        data = c.post("/api/review", json={"pgn": "1. e4 e5"}).json()
    assert [m["ply"] for m in data["key_moments"]] == [2, 3, 4, 5]
    assert [m["classification"] for m in data["key_moments"]] == [
        "blunder",
        "mistake",
        "inaccuracy",
        "mistake",
    ]
