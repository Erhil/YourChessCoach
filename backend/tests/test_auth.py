import sqlite3
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from test_puzzles import build_puzzles_db

from app.auth import service
from app.auth.tokens import ALPHABET, hash_token, new_token, normalize_token
from app.config import settings as default_settings
from app.db import MIGRATIONS, connect, migrate
from app.main import create_app

ADMIN = default_settings.admin_token
BAD = "Неверный логин или токен"
PGN = "1. e4 e5 2. Nf3 Nc6 *"
FEN = "6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1"
LESSON = """---
title: T
level: 1
---
Text

```chess
fen: 4k3/8/8/8/8/8/8/4K2R w - - 0 1
task: t
solution: Rh8+
hint: h
```
"""


@pytest.fixture
def cfg(tmp_path):
    pdb = tmp_path / "puzzles.db"
    build_puzzles_db(pdb)
    lessons = tmp_path / "lessons"
    lessons.mkdir()
    (lessons / "01-test.md").write_text(LESSON, encoding="utf-8")
    return replace(
        default_settings,
        app_db_path=tmp_path / "app.db",
        puzzles_db_path=pdb,
        frontend_dist=tmp_path / "dist",
        lessons_dir=lessons,
    )


@pytest.fixture
def app(cfg):
    return create_app(cfg)


def plain(app) -> TestClient:
    return TestClient(app, auto_login=False)


@pytest.fixture
def admin(app):
    c = plain(app)
    assert c.post("/api/admin/login", json={"token": ADMIN}).status_code == 200
    return c


def make_user(admin, login) -> dict:
    r = admin.post("/api/admin/users", json={"login": login})
    assert r.status_code == 201, r.text
    return r.json()


def login_as(app, user) -> TestClient:
    c = plain(app)
    r = c.post("/api/auth/login", json={"login": user["login"], "token": user["token"]})
    assert r.status_code == 200, r.text
    return c


@pytest.fixture
def pair(app, admin):
    a, b = make_user(admin, "alice"), make_user(admin, "bob")
    return login_as(app, a), login_as(app, b), a, b


def sql(cfg, query, args=()):
    conn = sqlite3.connect(cfg.app_db_path)
    try:
        with conn:
            return conn.execute(query, args).fetchall()
    finally:
        conn.close()


def test_token_format_and_normalising():
    token = new_token()
    groups = token.split("-")
    assert [len(g) for g in groups] == [4, 4, 4, 4]
    assert set("".join(groups)) <= set(ALPHABET)
    assert hash_token(token.upper()) == hash_token(token.replace("-", " ")) == hash_token(token)
    assert normalize_token(" K7M2-9QXP ") == "k7m29qxp"


def test_login_me_and_cookie_flags(app, admin):
    user = make_user(admin, "alice")
    c = plain(app)
    assert c.get("/api/auth/me").status_code == 401
    # dashes and case do not matter
    r = c.post(
        "/api/auth/login", json={"login": "Alice", "token": user["token"].replace("-", "").upper()}
    )
    assert r.status_code == 200
    assert r.json() == {"login": "alice"}
    cookie = r.headers["set-cookie"].lower()
    for part in ("session=", "httponly", "samesite=strict", "path=/", "max-age=2592000"):
        assert part in cookie
    assert "secure" not in cookie.replace("samesite", "")
    assert c.get("/api/auth/me").json() == {"login": "alice"}


def test_secure_cookie_when_enabled(cfg, app, admin):
    user = make_user(admin, "alice")
    c = plain(create_app(replace(cfg, cookie_secure=True)))
    r = c.post("/api/auth/login", json=user)
    assert "secure" in r.headers["set-cookie"].lower()


def test_wrong_login_and_wrong_token_look_the_same(app, admin):
    user = make_user(admin, "alice")
    c = plain(app)
    wrong_token = c.post("/api/auth/login", json={"login": "alice", "token": "aaaa-aaaa-aaaa-aaaa"})
    wrong_login = c.post("/api/auth/login", json={"login": "nobody", "token": user["token"]})
    for r in (wrong_token, wrong_login):
        assert r.status_code == 401
        assert r.json() == {"detail": BAD}
        assert "set-cookie" not in r.headers


def test_sessions_are_stored_hashed(cfg, app, admin):
    user = make_user(admin, "alice")
    c = login_as(app, user)
    sid = c.cookies.get("session")
    (row,) = sql(cfg, "SELECT id_hash, admin FROM sessions WHERE user_id IS NOT NULL")
    assert row[0] != sid and len(row[0]) == 64 and row[1] == 0
    assert sql(cfg, "SELECT token_hash FROM users")[0][0] == hash_token(user["token"])


def test_logout_ends_the_session_on_the_server(app, admin):
    c = login_as(app, make_user(admin, "alice"))
    sid = c.cookies.get("session")
    assert c.post("/api/auth/logout").status_code == 204
    assert c.get("/api/auth/me").status_code == 401
    replay = plain(app)
    replay.cookies.set("session", sid)
    assert replay.get("/api/auth/me").status_code == 401
    assert c.post("/api/auth/logout").status_code == 204  # idempotent


def test_expired_session_is_rejected_and_deleted(cfg, app, admin):
    c = login_as(app, make_user(admin, "alice"))
    sql(cfg, "UPDATE sessions SET expires_at = '2000-01-01T00:00:00Z' WHERE user_id IS NOT NULL")
    assert c.get("/api/auth/me").status_code == 401
    assert sql(cfg, "SELECT COUNT(*) FROM sessions WHERE user_id IS NOT NULL") == [(0,)]


def test_token_reset_kills_sessions_and_old_token(app, admin):
    user = make_user(admin, "alice")
    c1, c2 = login_as(app, user), login_as(app, user)
    other = login_as(app, make_user(admin, "bob"))
    r = admin.post(f"/api/admin/users/{user['id']}/token")
    new = r.json()["token"]
    assert new != user["token"]
    assert c1.get("/api/auth/me").status_code == 401
    assert c2.get("/api/auth/me").status_code == 401
    assert other.get("/api/auth/me").status_code == 200
    fresh = plain(app)
    assert (
        fresh.post("/api/auth/login", json={"login": "alice", "token": user["token"]}).status_code
        == 401
    )
    assert fresh.post("/api/auth/login", json={"login": "alice", "token": new}).status_code == 200
    assert admin.post("/api/admin/users/999/token").status_code == 404


def test_last_seen_updates_at_most_once_a_minute(cfg, app, admin):
    c = login_as(app, make_user(admin, "alice"))
    assert sql(cfg, "SELECT last_seen_at FROM users")[0][0] is None
    c.get("/api/auth/me")
    first = sql(cfg, "SELECT last_seen_at FROM users")[0][0]
    assert first
    sql(cfg, "UPDATE users SET last_seen_at = '2999-01-01T00:00:00Z'")
    c.get("/api/auth/me")
    assert sql(cfg, "SELECT last_seen_at FROM users")[0][0] == "2999-01-01T00:00:00Z"
    sql(cfg, "UPDATE users SET last_seen_at = '2000-01-01T00:00:00Z'")
    c.get("/api/auth/me")
    assert sql(cfg, "SELECT last_seen_at FROM users")[0][0] > "2020"


def test_admin_login_missing_wrong_right(cfg, app):
    off = plain(create_app(replace(cfg, admin_token="")))
    r = off.post("/api/admin/login", json={"token": ""})
    assert r.status_code == 503
    c = plain(app)
    assert c.post("/api/admin/login", json={"token": "nope"}).status_code == 401
    assert c.get("/api/admin/users").status_code == 401
    r = c.post("/api/admin/login", json={"token": ADMIN})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    for part in (
        "admin_session=",
        "httponly",
        "samesite=strict",
        "path=/api/admin",
        "max-age=43200",
    ):
        assert part in cookie
    assert c.get("/api/admin/users").status_code == 200
    assert c.post("/api/admin/logout").status_code == 204
    assert c.get("/api/admin/users").status_code == 401


def test_admin_and_user_sessions_do_not_mix(app, admin):
    user = make_user(admin, "alice")
    c = login_as(app, user)
    assert c.get("/api/admin/users").status_code == 401
    assert admin.get("/api/auth/me").status_code == 401
    assert admin.get("/api/games").status_code == 401
    # a user session id sent as the admin cookie is no admin session
    forged = plain(app)
    forged.cookies.set("admin_session", c.cookies.get("session"), path="/api/admin")
    assert forged.get("/api/admin/users").status_code == 401


def test_admin_creates_lists_and_shows_progress(app, admin):
    assert admin.get("/api/admin/users").json() == []
    user = make_user(admin, "Alice_1")
    assert user["login"] == "alice_1" and len(user["token"]) == 19
    assert admin.post("/api/admin/users", json={"login": "ALICE_1"}).status_code == 409
    for bad in ("a", "x" * 33, "bad name", "ёж", ""):
        assert admin.post("/api/admin/users", json={"login": bad}).status_code == 422
    c = login_as(app, user)
    c.post("/api/games", json={"pgn": PGN, "player_color": "white", "result": "*"})
    listing = admin.get("/api/admin/users").json()
    assert len(listing) == 1
    row = listing[0]
    assert set(row) == {
        "id", "login", "created_at", "last_seen_at", "mcp_key", "games", "puzzle_rating",
        "puzzles_solved", "mistakes_due", "mistakes_learned", "lessons_done",
    }  # fmt: skip
    assert row["games"] == 1 and row["puzzle_rating"] == 600 and row["last_seen_at"]
    assert row["mcp_key"] is False
    assert "token" not in row and "token_hash" not in row
    progress = admin.get(f"/api/admin/users/{user['id']}/progress").json()
    # The admin view has the all-time fields only, without the local-day calendar and weeks.
    own = c.get("/api/progress").json()
    assert progress == {k: v for k, v in own.items() if k not in ("calendar", "weeks")}
    assert progress["games"]["count"] == 1
    assert admin.get("/api/admin/users/999/progress").status_code == 404


def test_first_user_takes_rows_without_owner(cfg, app, admin):
    sql(
        cfg,
        "INSERT INTO games (player_color, result, moves_count, pgn) VALUES ('white', '*', 1, 'x')",
    )
    sql(
        cfg,
        "INSERT INTO puzzle_attempts (puzzle_id, solved, used_hint, puzzle_rating, rating_before,"
        " rating_after) VALUES ('p', 1, 0, 700, 600, 610)",
    )
    sql(cfg, "INSERT INTO user_ratings (scope, rating, attempts) VALUES ('overall', 610, 1)")
    sql(cfg, "INSERT INTO lesson_progress (slug, position) VALUES ('test', 0)")
    sql(
        cfg,
        "INSERT INTO mistakes (source, ref, fen, best_uci, best_san, created_at, due_at, reviews,"
        " lapses) VALUES ('play', 'r', 'f', 'e2e4', 'e4', 'n', '2000-01-01T00:00:00Z', 0, 0)",
    )
    first = make_user(admin, "alice")
    second = make_user(admin, "bob")
    for table in service.OWNED_TABLES:
        assert sql(cfg, f"SELECT user_id FROM {table}") == [(first["id"],)], table
    a, b = login_as(app, first), login_as(app, second)
    assert a.get("/api/games").json() != []
    assert a.get("/api/puzzles/rating").json()["overall"] == 610
    assert b.get("/api/games").json() == []
    assert b.get("/api/puzzles/rating").json()["overall"] == 600
    assert b.get("/api/mistakes/stats").json()["total"] == 0


def test_migration_keeps_data(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    for number, script in enumerate(MIGRATIONS[:7], start=1):
        conn.executescript("BEGIN;" + script + f"PRAGMA user_version = {number}; COMMIT;")
    conn.execute(
        "INSERT INTO games (player_color, result, moves_count, pgn) VALUES ('white', '*', 1, 'x')"
    )
    conn.execute(
        "INSERT INTO puzzle_attempts (puzzle_id, solved, used_hint, puzzle_rating, rating_before,"
        " rating_after) VALUES ('p', 1, 0, 700, 600, 610)"
    )
    conn.execute("INSERT INTO user_ratings VALUES ('overall', 610.5, 3), ('fork', 500, 1)")
    conn.execute(
        "INSERT INTO lesson_progress (slug, position, solved_at) VALUES ('a', 0, 't1'), ('a', 1, 't2')"
    )
    conn.execute(
        "INSERT INTO mistakes (id, source, ref, fen, best_uci, best_san, created_at, due_at,"
        " reviews, lapses, streak, learned_at) VALUES (7, 'play', 'r', 'f', 'e2e4', 'e4', 'n',"
        " 'd', 5, 1, 2, 'L')"
    )
    conn.commit()
    conn.close()
    migrate(path)
    conn = connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    count = lambda t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    assert [
        count(t)
        for t in ("games", "puzzle_attempts", "user_ratings", "lesson_progress", "mistakes")
    ] == [1, 1, 2, 2, 1]
    assert conn.execute(
        "SELECT scope, rating, attempts, user_id FROM user_ratings ORDER BY scope"
    ).fetchall()[1][:] == ("overall", 610.5, 3, None)
    assert conn.execute(
        "SELECT slug, position, solved_at FROM lesson_progress ORDER BY position"
    ).fetchall()[1][:] == ("a", 1, "t2")
    card = conn.execute(
        "SELECT id, reviews, lapses, streak, learned_at, user_id FROM mistakes"
    ).fetchone()
    assert tuple(card) == (7, 5, 1, 2, "L", None)
    # the keys now include user_id: two users may own the same scope, lesson position and card
    uid = service.create_user(conn, "u1", new_token())
    other = service.create_user(conn, "u2", new_token())
    assert (
        conn.execute("SELECT COUNT(*) FROM mistakes WHERE user_id = ?", (uid,)).fetchone()[0] == 1
    )
    with conn:
        for u in (other,):
            conn.execute(
                "INSERT INTO user_ratings (user_id, scope, rating, attempts) VALUES (?, 'overall', 1, 1)",
                (u,),
            )
            conn.execute(
                "INSERT INTO lesson_progress (user_id, slug, position) VALUES (?, 'a', 0)", (u,)
            )
            conn.execute(
                "INSERT INTO mistakes (user_id, source, ref, fen, best_uci, best_san, created_at,"
                " due_at, reviews, lapses) VALUES (?, 'play', 'r', 'f', 'e2e4', 'e4', 'n', 'd', 0, 0)",
                (u,),
            )
    with pytest.raises(sqlite3.IntegrityError), conn:
        conn.execute(
            "INSERT INTO user_ratings (user_id, scope, rating, attempts) VALUES (?, 'overall', 1, 1)",
            (other,),
        )
    conn.close()


def protected_routes(app):
    public = {("GET", "/api/health"), ("POST", "/api/auth/login"), ("POST", "/api/admin/login")}
    idempotent = {("POST", "/api/auth/logout"), ("POST", "/api/admin/logout")}
    for path, methods in app.openapi()["paths"].items():
        for method in sorted(m.upper() for m in methods):
            if path.startswith("/api/") and (method, path) not in public | idempotent:
                yield method, path


def test_every_api_route_needs_a_session(app):
    c = plain(app)
    routes = list(protected_routes(app))
    assert len(routes) >= 25
    for method, path in routes:
        url = path.replace("{user_id}", "1").replace("{slug}", "test").replace("{index}", "0")
        url = url.replace("{card_id}", "1").replace("{puzzle_id}", "p00")
        r = c.request(method, url, json={})
        assert r.status_code == 401, (method, path, r.status_code)


def test_bench_is_admin_only(app, admin, pair):
    a, _, _, _ = pair
    assert a.get("/api/admin/bench/results").status_code == 401
    assert a.post("/api/admin/bench/default", json={"model": "m"}).status_code == 401
    assert admin.get("/api/admin/bench/results").status_code in (200, 404)


def test_users_cannot_reach_each_others_data(cfg, pair, admin):
    a, b, ua, ub = pair
    # A creates a game, a card, a puzzle attempt (a miss makes a card) and lesson progress.
    game = a.post("/api/games", json={"pgn": PGN, "player_color": "white", "result": "*"}).json()[
        "id"
    ]
    card = a.post(
        "/api/mistakes",
        json={"source": "play", "fen": FEN, "best_uci": "a1a8", "classification": "blunder"},
    ).json()["id"]
    assert a.post("/api/puzzles/p00/attempt", json={"solved": False}).status_code == 200
    assert a.post("/api/lessons/test/positions/0").json()["solved"] == [0]
    a_rating = a.get("/api/puzzles/rating").json()
    assert a_rating["attempts"] == 1 and a_rating["overall"] != 600

    # B sees nothing of it.
    assert b.get("/api/games").json() == []
    assert b.post("/api/review", json={"game_id": game}).status_code == 404
    deck = b.get("/api/mistakes/next").json()
    assert deck["card"] is None and deck["due"] == 0 and deck["today"]["reviewed"] == 0
    assert b.get("/api/mistakes/stats").json() == {"total": 0, "due": 0, "learned": 0}
    assert b.post(f"/api/mistakes/{card}/answer", json={"uci": "a1a8"}).status_code == 404
    assert b.get("/api/puzzles/rating").json() == {"overall": 600, "attempts": 0, "themes": []}
    assert b.get("/api/lessons/test").json()["solved"] == []
    assert next(x for x in b.get("/api/lessons").json())["solved"] == 0
    progress = b.get("/api/progress").json()
    assert progress["games"]["count"] == 0 and progress["puzzles"]["attempts"] == 0
    assert progress["mistakes"]["total"] == 0 and progress["lessons"]["completed"] == 0
    assert progress["themes"] == [] and progress["puzzles"]["history"] == []
    assert progress["calendar"] == [] and all(w["puzzles_solved"] == 0 for w in progress["weeks"])
    assert b.get("/api/puzzles/next").json()["user_rating"] == 600

    # B's own writes do not touch A, and the same position gives B its own card.
    mine = b.post(
        "/api/mistakes",
        json={"source": "play", "fen": FEN, "best_uci": "a1a8", "classification": "blunder"},
    ).json()
    assert mine["created"] is True and mine["id"] != card
    b.post("/api/puzzles/p00/attempt", json={"solved": True})
    b.post("/api/lessons/test/positions/0")
    assert a.get("/api/puzzles/rating").json() == a_rating
    assert a.get("/api/mistakes/stats").json()["total"] == 2  # the play card and the missed puzzle
    assert b.get("/api/mistakes/stats").json()["total"] == 1
    assert len(a.get("/api/games").json()) == 1

    # Owners in the database.
    assert sql(cfg, "SELECT user_id FROM games") == [(ua["id"],)]
    assert sorted(
        r[0] for r in sql(cfg, "SELECT user_id FROM user_ratings WHERE scope = 'overall'")
    ) == sorted([ua["id"], ub["id"]])
    own = b.get("/api/progress").json()
    assert own.pop("calendar") and len(own.pop("weeks")) == 8
    assert admin.get(f"/api/admin/users/{ub['id']}/progress").json() == own
