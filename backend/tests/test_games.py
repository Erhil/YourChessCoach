import sqlite3
from contextlib import closing
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
    assert raw.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
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


def test_retry_merges_late_analysis_atomically(client, db_path):
    payload = body(client_id="late-analysis")
    first = client.post("/api/games", json=payload)
    assert first.status_code == 201
    gid = first.json()["id"]
    error = {"ply": 3, "best_uci": "f1c4", "classification": "blunder"}
    late = {**payload, "blunders": 1, "errors": [error]}

    # The first valid event and blunder update must roll back with the malformed event.
    invalid = {
        **late,
        "errors": [{**error, "ply": 1, "best_uci": "d2d4"}, {**error, "best_uci": "a1a8"}],
    }
    assert client.post("/api/games", json=invalid).status_code == 422
    conflict = {**late, "pgn": "1. d4 d5 2. Nf3 Nc6 *"}
    assert client.post("/api/games", json=conflict).status_code == 409
    with closing(connect(db_path)) as db:
        assert tuple(db.execute("SELECT pgn, blunders FROM games").fetchone()) == (PGN, None)
        assert db.execute("SELECT COUNT(*) FROM mistake_events").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM mistakes").fetchone()[0] == 0

    for delivery in (late, late, payload, {**late, "blunders": 2}):
        retry = client.post("/api/games", json=delivery)
        assert retry.status_code == 201 and retry.json() == first.json()
    with closing(connect(db_path)) as db:
        assert tuple(db.execute("SELECT pgn, blunders FROM games").fetchone()) == (PGN, 1)
        events = db.execute(
            "SELECT game_id, ply, origin, prefix_uci, played_uci, best_uci FROM mistake_events"
        ).fetchall()
        assert [tuple(event) for event in events] == [(gid, 3, "play", "e2e4 e7e5", "g1f3", "f1c4")]


def test_game_save_rejects_null_move_before_an_error(client):
    error = {"ply": 3, "best_uci": "e2e4", "classification": "blunder"}
    pgn = "1. -- e5 2. Nf3 Nc6 *"
    assert client.post("/api/games", json=body(pgn, errors=[error])).status_code == 422
    assert client.post("/api/games", json=body(pgn)).status_code == 422
    assert client.get("/api/games").json() == []
    assert client.get("/api/mistakes/stats").json()["total"] == 0


def test_game_error_accepts_legal_black_to_move_fen_start(client, db_path):
    start = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
    pgn = f'[SetUp "1"]\n[FEN "{start}"]\n\n1... e5 2. Nf3 *'
    errors = [{"ply": 1, "best_uci": "c7c5", "classification": "mistake"}]
    response = client.post("/api/games", json=body(pgn, player_color="black", errors=errors))
    assert response.status_code == 201, response.text
    with closing(connect(db_path)) as db:
        event = db.execute(
            "SELECT start_fen, prefix_uci, played_uci FROM mistake_events"
        ).fetchone()
        assert tuple(event) == (start, "", "e7e5")


def test_late_error_for_older_game_keeps_newer_occurrence_review_history(client, db_path):
    old = body(client_id="older-game")
    first = client.post("/api/games", json=old)
    assert first.status_code == 201
    errors = [{"ply": 3, "best_uci": "f1c4", "classification": "mistake"}]
    assert (
        client.post(
            "/api/games", json={**old, "client_id": "newer-game", "errors": errors}
        ).status_code
        == 201
    )
    card = client.get("/api/mistakes/next").json()["card"]
    with closing(connect(db_path)) as db, db:
        db.execute(
            "UPDATE mistakes SET reviews = 3, streak = 3, review_version = 3,"
            " learned_at = '2026-01-01', due_at = '2099-01-01' WHERE id = ?",
            (card["id"],),
        )
    retry = client.post("/api/games", json={**old, "errors": errors})
    assert retry.status_code == 201 and retry.json() == first.json()
    with closing(connect(db_path)) as db:
        events = db.execute("SELECT card_id FROM mistake_events").fetchall()
        assert [event["card_id"] for event in events] == [card["id"]] * 2
        assert tuple(
            db.execute(
                "SELECT reviews, streak, review_version, learned_at, due_at FROM mistakes"
            ).fetchone()
        ) == (3, 3, 3, "2026-01-01", "2099-01-01")


def test_new_game_error_reopens_same_card_without_changing_review_history(client, db_path):
    payload = body(
        client_id="first-game",
        errors=[{"ply": 3, "best_uci": "f1c4", "classification": "mistake"}],
    )
    first = client.post("/api/games", json=payload)
    assert first.status_code == 201
    card = client.get("/api/mistakes/next").json()["card"]
    assert card["played_san"] == "Nf3"
    with closing(connect(db_path)) as db, db:
        db.execute(
            "UPDATE mistakes SET reviews = 5, lapses = 1, review_version = 5, streak = 3,"
            " learned_at = '2026-01-01', due_at = '2099-01-01' WHERE id = ?",
            (card["id"],),
        )
    assert client.post("/api/games", json=payload).json() == first.json()
    assert client.get("/api/mistakes/stats").json() == {"total": 1, "learned": 1, "due": 0}
    second = client.post("/api/games", json={**payload, "client_id": "second-game"})
    assert second.status_code == 201 and second.json() != first.json()
    reopened = client.get("/api/mistakes/next").json()["card"]
    assert reopened["id"] == card["id"] and reopened["review_version"] == 6
    stale = client.post(
        f"/api/mistakes/{card['id']}/answer", json={"uci": "f1c4", "review_version": 5}
    )
    assert stale.status_code == 409
    with closing(connect(db_path)) as db:
        assert tuple(db.execute("SELECT reviews, lapses, streak FROM mistakes").fetchone()) == (
            5,
            1,
            0,
        )
        assert db.execute("SELECT COUNT(*) FROM mistake_events").fetchone()[0] == 2


def test_game_errors_require_legal_moves_by_owner_and_roll_back_whole_save(client):
    valid = {"ply": 1, "best_uci": "d2d4", "classification": "blunder"}
    for invalid in (
        {**valid, "ply": 2, "best_uci": "d7d5"},
        {**valid, "ply": 3, "best_uci": "f1b7"},
        {**valid, "ply": 5},
    ):
        assert client.post("/api/games", json=body(errors=[valid, invalid])).status_code == 422
    assert (
        client.post("/api/games", json=body(expected_login="other", errors=[valid])).status_code
        == 409
    )
    assert client.get("/api/games").json() == []
    assert client.get("/api/mistakes/stats").json()["total"] == 0
