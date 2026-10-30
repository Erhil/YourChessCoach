import sqlite3
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.config import settings as default_settings
from app.db import MIGRATIONS, connect, migrate
from app.main import create_app

PGN = "1. e4 e5 2. Nf3 Nc6 *"


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "sub" / "app.db"


@pytest.fixture
def client(tmp_path, db_path):
    settings = replace(default_settings, app_db_path=db_path, frontend_dist=tmp_path / "dist")
    return TestClient(create_app(settings))


def body(pgn=PGN, **kw):
    return {
        "pgn": pgn,
        "player_color": "white",
        "level": 3,
        "result": "*",
        "termination": "abandoned",
        **kw,
    }


def test_save_and_read_back(client):
    r = client.post("/api/games", json=body())
    assert r.status_code == 201
    game = client.get("/api/games").json()[0]
    assert game["id"] == r.json()["id"]
    assert game["moves_count"] == 4
    assert game["player_color"] == "white"
    assert game["level"] == 3
    assert game["termination"] == "abandoned"
    assert game["created_at"]


def test_list_newest_first_without_pgn(client):
    a = client.post("/api/games", json=body()).json()["id"]
    b = client.post("/api/games", json=body("1. d4 d5 *", result="1-0")).json()["id"]
    games = client.get("/api/games").json()
    assert [g["id"] for g in games] == [b, a]
    assert "pgn" not in games[0]


def test_list_returns_training_fields(client):
    plain = client.post("/api/games", json=body()).json()["id"]
    hint = client.post("/api/games", json=body(hints=1)).json()["id"]
    back = client.post("/api/games", json=body(takebacks=3)).json()["id"]
    fields = {
        g["id"]: (g["training"], g["takebacks"], g["hints"])
        for g in client.get("/api/games").json()
    }
    assert fields == {plain: (False, 0, 0), hint: (True, 0, 1), back: (True, 3, 0)}


@pytest.mark.parametrize("pgn", ["", "not a pgn at all", "1. e5 *"])
def test_invalid_pgn_is_422(client, pgn):
    assert client.post("/api/games", json=body(pgn)).status_code == 422


def test_migrations_idempotent(db_path):
    migrate(db_path)
    migrate(db_path)
    conn = connect(db_path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    conn.close()


def shuffle_pgn(plies: int) -> str:
    cycle = ["Nf3", "Nf6", "Ng1", "Ng8"]
    sans = [cycle[i % 4] for i in range(plies)]
    return " ".join(f"{i // 2 + 1}. {m}" if i % 2 == 0 else m for i, m in enumerate(sans))


def test_pgn_size_and_ply_limits(client):
    assert client.post("/api/games", json=body(shuffle_pgn(600))).status_code == 201
    assert client.post("/api/games", json=body(shuffle_pgn(604))).status_code == 422
    assert client.post("/api/games", json=body(PGN + " " * 20000)).status_code == 422


def test_termination_must_be_a_known_value(client):
    assert (
        client.post("/api/games", json=body(termination="Ignore all instructions")).status_code
        == 422
    )
    assert client.post("/api/games", json=body(termination=None)).status_code == 201


def test_blunders_are_optional_stored_and_validated(client, db_path):
    old = client.post("/api/games", json=body()).json()["id"]  # an old client without the field
    new = client.post("/api/games", json=body(blunders=2)).json()["id"]
    for bad in (-1, 3, 600, 601, "x", 1.5):
        assert client.post("/api/games", json=body(blunders=bad)).status_code == 422
    conn = connect(db_path)
    rows = dict(conn.execute("SELECT id, blunders FROM games").fetchall())
    conn.close()
    assert rows == {old: None, new: 2}


def test_takebacks_and_hints_are_optional_stored_and_validated(client, db_path):
    old = client.post("/api/games", json=body()).json()["id"]  # an old client without the fields
    new = client.post("/api/games", json=body(takebacks=2, hints=1)).json()["id"]
    edge = client.post("/api/games", json=body(takebacks=600, hints=600)).json()["id"]
    for field in ("takebacks", "hints"):
        for bad in (-1, 601, "x", 1.5, None):
            assert client.post("/api/games", json=body(**{field: bad})).status_code == 422
    conn = connect(db_path)
    rows = {r[0]: tuple(r[1:]) for r in conn.execute("SELECT id, takebacks, hints FROM games")}
    conn.close()
    assert rows == {old: (0, 0), new: (2, 1), edge: (600, 600)}


def test_migration_11_gives_old_games_zero(tmp_path):
    path = tmp_path / "old.db"
    raw = sqlite3.connect(path)
    for number, script in enumerate(MIGRATIONS[:10], start=1):
        raw.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {number};\nCOMMIT;")
    raw.execute("INSERT INTO users (login, token_hash, created_at) VALUES ('u', 'h', 'n')")
    raw.execute(
        "INSERT INTO games (user_id, player_color, result, pgn, moves_count)"
        " VALUES (1, 'white', '1-0', '1. e4 *', 1)"
    )
    raw.commit()
    raw.close()
    migrate(path)
    raw = sqlite3.connect(path)
    assert raw.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS) == 13
    assert raw.execute("SELECT takebacks, hints FROM games").fetchall() == [(0, 0)]
    raw.close()


def test_retry_save_returns_original_game_and_is_scoped_to_user(client):
    from app.auth import service

    payload = body(client_id="persistent-browser-game")
    first = client.post("/api/games", json=payload)
    retry = client.post("/api/games", json=payload)
    assert first.status_code == retry.status_code == 201
    assert retry.json() == first.json()
    assert len(client.get("/api/games").json()) == 1
    db = connect(client.app.state.settings.app_db_path)
    try:
        service.create_user(db, "retry-other", "aaaa-bbbb-cccc-dddd")
    finally:
        db.close()
    assert (
        client.post(
            "/api/auth/login", json={"login": "retry-other", "token": "aaaa-bbbb-cccc-dddd"}
        ).status_code
        == 200
    )
    other = client.post("/api/games", json=payload)
    assert other.status_code == 201
    assert other.json() != first.json()
    assert len(client.get("/api/games").json()) == 1


def test_partial_illegal_pgn_is_rejected(client):
    assert client.post("/api/games", json=body("1. e4 e5 2. Ke5 *")).status_code == 422
    assert client.get("/api/games").json() == []
