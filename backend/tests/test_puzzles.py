import sqlite3
from dataclasses import replace

import chess
import pytest
from fastapi.testclient import TestClient

from app.config import settings as default_settings
from app.main import create_app
from app.puzzles.rating import START_RATING, expected_score, k_factor, score, update_rating
from app.puzzles.themes import OFFERED, THEME_NAMES

START_FEN = chess.STARTING_FEN
# Real-format puzzle: the FEN is before the opponent's move d2e4 (white); the player is black.
REAL = (
    "yZXbn",
    "rn3rk1/1pp2ppp/1b6/pP2p1q1/P7/2PPPP1P/R2NK3/3Q1B1R w - - 3 16",
    "d2e4 g5e3",
    499,
    "mate mateIn1 middlegame oneMove swallowstailMate",
)


def build_puzzles_db(path, with_real=True):
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE puzzles (id TEXT PRIMARY KEY, fen TEXT NOT NULL, moves TEXT NOT NULL,
          rating INTEGER, rating_deviation INTEGER, popularity INTEGER, nb_plays INTEGER,
          themes TEXT, opening_tags TEXT);
        CREATE TABLE puzzle_themes (puzzle_id TEXT NOT NULL, theme TEXT NOT NULL);
        """
    )
    rows = [REAL] if with_real else []
    # 40 puzzles: ratings 400..1180, every other one is a fork, every 4th one is also a pin.
    for i in range(40):
        themes = "fork short" if i % 2 == 0 else "mateIn2 short"
        if i % 4 == 0:
            themes += " pin"
        rows.append((f"p{i:02d}", START_FEN, "e2e4 e7e5 g1f3", 400 + i * 20, themes))
    for pid, fen, moves, rating, themes in rows:
        # p00..p09: Italian Game (family + variation), p10..p12: Ruy Lopez, the rest: no opening
        n = int(pid[1:]) if pid[1:].isdigit() else 99
        tags = (
            "Italian_Game Italian_Game_Classical_Variation"
            if n < 10
            else "Ruy_Lopez"
            if n < 13
            else ""
        )
        conn.execute(
            "INSERT INTO puzzles VALUES (?, ?, ?, ?, 0, 0, 0, ?, ?)",
            (pid, fen, moves, rating, themes, tags),
        )
        conn.executemany(
            "INSERT INTO puzzle_themes VALUES (?, ?)", [(pid, t) for t in themes.split()]
        )
    conn.commit()
    conn.close()


@pytest.fixture
def client(tmp_path):
    pdb = tmp_path / "puzzles.db"
    build_puzzles_db(pdb)
    settings = replace(
        default_settings,
        app_db_path=tmp_path / "app.db",
        puzzles_db_path=pdb,
        frontend_dist=tmp_path / "dist",
    )
    return TestClient(create_app(settings))


def test_theme_names_cover_offered_keys():
    assert "short" not in OFFERED and "fork" in OFFERED and "mateIn1" in OFFERED
    assert all(THEME_NAMES[k] for k in OFFERED)


def test_first_move_belongs_to_opponent(client):
    data = client.get("/api/puzzles/next?theme=swallowstailMate").json()
    assert data["id"] == "yZXbn"
    assert data["opponent_move"] == "d2e4"
    assert data["solution"] == ["g5e3"]
    assert data["player_color"] == "black"
    board = chess.Board(data["fen"])
    first = chess.Move.from_uci(data["solution"][0])
    assert first not in board.legal_moves  # white is to move in the stored FEN
    board.push_uci(data["opponent_move"])
    assert first in board.legal_moves


def test_rating_math():
    assert expected_score(600, 600) == 0.5
    assert update_rating(600, 0, 600, 1.0) == pytest.approx(600 + k_factor(0) / 2)
    assert update_rating(600, 0, 600, 0.0) == pytest.approx(600 - k_factor(0) / 2)
    assert [k_factor(n) for n in (0, 10, 20, 100)] == [60, 40, 20, 20]
    assert (score(True, False), score(True, True), score(False, False)) == (1.0, 0.5, 0.0)
    assert START_RATING == 600


def test_themes_endpoint(client):
    themes = client.get("/api/puzzles/themes").json()
    assert {t["key"] for t in themes} == {
        "fork",
        "mateIn2",
        "pin",
        "mateIn1",
        "mate",
        "swallowstailMate",
    }
    assert [t["name"] for t in themes] == sorted(t["name"] for t in themes)
    assert next(t for t in themes if t["key"] == "fork")["count"] == 20


def test_next_respects_window_and_theme(client):
    for _ in range(15):
        data = client.get("/api/puzzles/next?theme=fork").json()
        assert 450 <= data["rating"] <= 750
        assert "fork" in {t["key"] for t in data["themes"]}
        assert data["user_rating"] == 600
    # 600 +- 150 holds p10..p27 and the real puzzle (499); mixed mode too.
    assert 450 <= client.get("/api/puzzles/next").json()["rating"] <= 750


def test_next_widens_window(client):
    # Raise the overall rating far above every puzzle.
    for _ in range(40):
        client.post("/api/puzzles/p39/attempt", json={"solved": True, "used_hint": False})
    data = client.get("/api/puzzles/next").json()
    assert data["user_rating"] > 1300
    assert data["rating"] >= 1000  # the window widens, the nearest puzzles are the hardest ones


def test_next_skips_recent_attempts(client):
    seen = set()
    for _ in range(10):
        data = client.get("/api/puzzles/next?theme=pin").json()
        assert data["id"] not in seen
        seen.add(data["id"])
        client.post(
            f"/api/puzzles/{data['id']}/attempt", json={"solved": False, "used_hint": False}
        )
    assert len(seen) == 10  # all 10 pin puzzles were served once
    assert (
        client.get("/api/puzzles/next?theme=pin").status_code == 404
    )  # none left that is not recent


def test_attempt_updates_overall_and_theme(client):
    r = client.post("/api/puzzles/p00/attempt", json={"solved": True, "used_hint": False})
    assert r.status_code == 200
    out = r.json()
    assert out["rating_before"] == 600 and out["rating_after"] > 600 and out["delta"] > 0
    assert {t["key"] for t in out["themes"]} == {"fork", "pin"}
    rating = client.get("/api/puzzles/rating").json()
    assert rating["overall"] == out["rating_after"] and rating["attempts"] == 1
    assert {t["key"]: t["attempts"] for t in rating["themes"]} == {"fork": 1, "pin": 1}
    # the theme has a rating now, so `next` uses it
    assert (
        client.get("/api/puzzles/next?theme=fork").json()["user_rating"]
        == out["themes"][0]["rating"]
    )
    failed = client.post(
        "/api/puzzles/p02/attempt", json={"solved": False, "used_hint": True}
    ).json()
    assert failed["delta"] < 0


def test_openings_list_and_filter(client, monkeypatch):
    monkeypatch.setattr("app.puzzles.routes.MIN_OPENING_PUZZLES", 3)
    openings = client.get("/api/puzzles/openings").json()
    assert openings == [
        {"key": "Italian_Game", "name": "Итальянская партия", "count": 10},
        {"key": "Ruy_Lopez", "name": "Испанская партия", "count": 3},
    ]
    for _ in range(10):
        data = client.get("/api/puzzles/next?opening=Italian_Game").json()
        assert data["id"] in {f"p{i:02d}" for i in range(10)}
    # combined with a theme: fork puzzles among p00..p09 are the even ones
    data = client.get("/api/puzzles/next?opening=Italian_Game&theme=fork").json()
    assert int(data["id"][1:]) % 2 == 0
    # the variation tag alone is not a family
    assert (
        client.get("/api/puzzles/next?opening=Italian_Game_Classical_Variation").status_code == 404
    )
    assert client.get("/api/puzzles/next?opening=Nope").status_code == 404


def test_openings_below_minimum_are_hidden(client):
    assert client.get("/api/puzzles/openings").json() == []  # 200 puzzles per family needed


def test_unknown_puzzle_is_404(client):
    r = client.post("/api/puzzles/nope/attempt", json={"solved": True, "used_hint": False})
    assert r.status_code == 404


def test_missing_puzzle_db_is_503(tmp_path):
    settings = replace(
        default_settings,
        app_db_path=tmp_path / "app.db",
        puzzles_db_path=tmp_path / "none.db",
        frontend_dist=tmp_path / "dist",
    )
    c = TestClient(create_app(settings))
    for url in ("/api/puzzles/themes", "/api/puzzles/next", "/api/puzzles/openings"):
        r = c.get(url)
        assert r.status_code == 503
        assert "import_puzzles.py" in r.json()["detail"]


def test_attempt_retry_is_idempotent_and_conflicts_are_rejected(client):
    url = "/api/puzzles/p00/attempt"
    body = {"solved": True, "used_hint": False, "client_id": "attempt-a"}
    first = client.post(url, json=body)
    assert first.status_code == 200
    # The client lost the first response. Retry after another legitimate attempt.
    second = client.post(url, json={**body, "client_id": "attempt-b"})
    assert second.status_code == 200
    assert client.post(url, json=body).json() == first.json()
    assert client.get("/api/puzzles/rating").json()["attempts"] == 2
    assert client.post(url, json={**body, "solved": False}).status_code == 409
    assert client.post("/api/puzzles/p01/attempt", json=body).status_code == 409
    assert client.get("/api/puzzles/rating").json()["attempts"] == 2


def test_failed_attempt_and_card_commit_together_or_retry(client):
    path = client.app.state.settings.app_db_path
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TRIGGER reject_card BEFORE INSERT ON mistakes "
        "BEGIN SELECT RAISE(ABORT, 'card unavailable'); END"
    )
    conn.commit()
    body = {"solved": False, "client_id": "atomic-failure"}
    with pytest.raises(sqlite3.IntegrityError, match="card unavailable"):
        client.post("/api/puzzles/p00/attempt", json=body)
    for table in ("puzzle_receipts", "puzzle_attempts", "user_ratings", "mistakes"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    conn.execute("DROP TRIGGER reject_card")
    conn.commit()
    first = client.post("/api/puzzles/p00/attempt", json=body)
    assert first.status_code == 200
    assert client.post("/api/puzzles/p00/attempt", json=body).json() == first.json()
    for table in ("puzzle_receipts", "puzzle_attempts", "mistakes"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 1
    assert (
        conn.execute("SELECT attempts FROM user_ratings WHERE scope = 'overall'").fetchone()[0] == 1
    )
    conn.close()
