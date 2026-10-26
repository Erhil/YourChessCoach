import json
import sqlite3
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from test_auth import LESSON, login_as, make_user, plain, sql
from test_puzzles import build_puzzles_db

import app.puzzles.routes as puzzle_routes
from app.activity.days import local_today, server_tz
from app.auth.tokens import hash_secret
from app.config import settings as default_settings
from app.main import create_app
from app.mcp.tools import ToolError, _eval_words
from app.mistakes.srs import now_utc

TSV = (
    "eco\tname\tpgn\n"
    "B00\tKing's Pawn\t1. e4\n"
    "C50\tItalian Game\t1. e4 e5 2. Nf3 Nc6 3. Bc4\n"
    "D30\tQueen's Gambit Declined\t1. d4 d5 2. c4 e6\n"
)
ITALIAN = "1. e4 e5 2. Nf3 Nc6 3. Bc4 *"
QGD = "1. d4 d5 2. c4 e6 *"
MATE = "1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7#"
START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


@pytest.fixture(autouse=True)
def _few_puzzles_make_a_family(monkeypatch):
    # The test puzzle db has 10 Italian Game puzzles; the real minimum is 200.
    monkeypatch.setattr(puzzle_routes, "MIN_OPENING_PUZZLES", 5)


@pytest.fixture
def mcfg(tmp_path):
    """Settings with a puzzle db, one lesson (slug "test") and an openings book."""
    data, lessons = tmp_path / "data", tmp_path / "lessons"
    data.mkdir()
    lessons.mkdir()
    (data / "openings.tsv").write_text(TSV, encoding="utf-8")
    (lessons / "01-test.md").write_text(LESSON, encoding="utf-8")
    build_puzzles_db(tmp_path / "puzzles.db")
    return replace(
        default_settings,
        app_data_dir=data,
        app_db_path=tmp_path / "app.db",
        puzzles_db_path=tmp_path / "puzzles.db",
        frontend_dist=tmp_path / "dist",
        lessons_dir=lessons,
    )


@pytest.fixture
def app(mcfg):
    return create_app(mcfg)


@pytest.fixture
def admin(app):
    c = plain(app)
    assert c.post("/api/admin/login", json={"token": app.state.settings.admin_token}).status_code
    return c


class FakePool:
    def __init__(self):
        self.calls = []
        self.movetimes = []

    def analyse(self, board, depth=None, movetime_ms=None, multipv=1):
        self.calls.append((board.fen(), depth, multipv))
        self.movetimes.append(movetime_ms)
        move = next(iter(board.legal_moves))
        san = board.san(move)
        lines = [
            {
                "rank": i,
                "score": {"cp": 40 * i, "mate": None},
                "pv_san": [san],
                "pv_uci": [move.uci()],
            }
            for i in range(1, multipv + 1)
        ]
        return depth or 0, lines

    def close(self):
        pass


@pytest.fixture
def duo(app, admin):
    """Two users with their own data and their own MCP keys."""
    out = []
    for login, pgn, color in (("alice", ITALIAN, "white"), ("bob", QGD, "black")):
        user = make_user(admin, login)
        c = login_as(app, user)
        gid = c.post(
            "/api/games",
            json={"pgn": pgn, "player_color": color, "level": 800, "result": "1-0"},
        ).json()["id"]
        key = c.post("/api/mcp-key").json()["key"]
        out.append((c, key, gid))
    return out


def rpc(app, key, method, params=None, msg_id=1, headers=None):
    c = plain(app)
    h = {"Authorization": f"Bearer {key}"} if key else {}
    return c.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}},
        headers={**h, **(headers or {})},
    )


def call(app, key, name, **args):
    """Call a tool; return (is_error, parsed JSON or the error text)."""
    r = rpc(app, key, "tools/call", {"name": name, "arguments": args})
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    text = result["content"][0]["text"]
    return result["isError"], (text if result["isError"] else json.loads(text))


# ------------------------------------------------------------------ keys


def test_key_create_replace_delete(app, admin, mcfg):
    user = make_user(admin, "alice")
    c = login_as(app, user)
    assert c.get("/api/mcp-key").json() == {"exists": False, "created_at": None}
    first = c.post("/api/mcp-key").json()["key"]
    state = c.get("/api/mcp-key").json()
    assert state["exists"] and state["created_at"]
    assert "key" not in state
    assert rpc(app, first, "ping").status_code == 200

    second = c.post("/api/mcp-key").json()["key"]
    assert second != first
    assert rpc(app, first, "ping").status_code == 401
    assert rpc(app, second, "ping").status_code == 200

    assert c.delete("/api/mcp-key").status_code == 204
    assert c.get("/api/mcp-key").json()["exists"] is False
    assert rpc(app, second, "ping").status_code == 401


def test_only_the_hash_is_stored(app, admin, mcfg):
    c = login_as(app, make_user(admin, "alice"))
    key = c.post("/api/mcp-key").json()["key"]
    assert len(key) >= 43
    (row,) = sql(mcfg, "SELECT mcp_key_hash FROM users WHERE login = 'alice'")
    assert row[0] == hash_secret(key) and key not in row[0]
    dump = sqlite3.connect(mcfg.app_db_path).iterdump()
    assert not any(key in line for line in dump)


def test_key_routes_need_a_session(app):
    c = plain(app)
    assert c.get("/api/mcp-key").status_code == 401
    assert c.post("/api/mcp-key").status_code == 401
    assert c.delete("/api/mcp-key").status_code == 401
    assert c.get("/api/plan").status_code == 401


def test_admin_sees_and_revokes_the_key(app, admin):
    a, b = make_user(admin, "alice"), make_user(admin, "bob")
    ca = login_as(app, a)
    key = ca.post("/api/mcp-key").json()["key"]
    users = {u["login"]: u for u in admin.get("/api/admin/users").json()}
    assert users["alice"]["mcp_key"] is True and users["bob"]["mcp_key"] is False
    assert admin.delete(f"/api/admin/users/{b['id']}/mcp-key").status_code == 204
    assert admin.delete("/api/admin/users/999/mcp-key").status_code == 404
    assert admin.delete(f"/api/admin/users/{a['id']}/mcp-key").status_code == 204
    assert rpc(app, key, "ping").status_code == 401
    users = {u["login"]: u for u in admin.get("/api/admin/users").json()}
    assert users["alice"]["mcp_key"] is False
    assert plain(app).delete(f"/api/admin/users/{a['id']}/mcp-key").status_code == 401


def test_token_reset_keeps_the_mcp_key(app, admin):
    user = make_user(admin, "alice")
    key = login_as(app, user).post("/api/mcp-key").json()["key"]
    assert admin.post(f"/api/admin/users/{user['id']}/token").status_code == 200
    assert rpc(app, key, "ping").status_code == 200


# ------------------------------------------------------------------ authentication of /mcp


def test_no_key_or_wrong_key_is_401(app):
    for headers in ({}, {"Authorization": "Bearer nope"}, {"Authorization": "Basic abc"}):
        r = plain(app).post(
            "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}, headers=headers
        )
        assert r.status_code == 401
        assert r.headers["www-authenticate"] == "Bearer"


def test_failed_keys_are_rate_limited(app, duo):
    _, key, _ = duo[0]
    for _i in range(5):
        assert rpc(app, "wrong-key", "ping").status_code == 401
    blocked = rpc(app, key, "ping")  # the right key too: the client IP is locked
    assert blocked.status_code == 429 and "retry-after" in blocked.headers


def test_cookie_session_does_not_open_mcp_and_key_does_not_open_api(app, duo):
    cookie_client, key, _ = duo[0]
    r = cookie_client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code == 401
    keyed = plain(app)
    for path in ("/api/progress", "/api/games", "/api/plan", "/api/auth/me", "/api/mcp-key"):
        assert keyed.get(path, headers={"Authorization": f"Bearer {key}"}).status_code == 401


def test_origin_must_match_the_host(app, duo):
    _, key, _ = duo[0]
    body = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    c = plain(app)
    auth = {"Authorization": f"Bearer {key}"}
    assert c.post("/mcp", json=body, headers=auth).status_code == 200  # no Origin
    same = {**auth, "Origin": "http://testserver"}
    assert c.post("/mcp", json=body, headers=same).status_code == 200
    evil = {**auth, "Origin": "http://evil.example"}
    assert c.post("/mcp", json=body, headers=evil).status_code == 403
    assert c.get("/mcp", headers=evil).status_code == 403


def test_body_limit_applies(app, duo):
    _, key, _ = duo[0]
    big = "x" * (1024 * 1024 + 10)
    r = plain(app).post("/mcp", content=big, headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 413


# ------------------------------------------------------------------ protocol


def test_handshake_and_lists(app, duo):
    _, key, _ = duo[0]
    init = rpc(app, key, "initialize", {"protocolVersion": "2025-06-18"}).json()["result"]
    assert init["protocolVersion"] == "2025-06-18" and "tools" in init["capabilities"]
    other = rpc(app, key, "initialize", {"protocolVersion": "1999-01-01"}).json()["result"]
    assert other["protocolVersion"] == "2025-11-25"
    c = plain(app)
    note = c.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert note.status_code == 202 and note.content == b""
    names = {t["name"] for t in rpc(app, key, "tools/list").json()["result"]["tools"]}
    assert names == {
        "get_profile",
        "list_games",
        "review_game",
        "analyse_position",
        "get_plan",
        "save_plan",
    }
    prompts = rpc(app, key, "prompts/list").json()["result"]["prompts"]
    assert [p["name"] for p in prompts] == ["weekly_review"]
    got = rpc(app, key, "prompts/get", {"name": "weekly_review"}).json()["result"]
    text = got["messages"][0]["content"]["text"]
    assert "get_profile" in text and "save_plan" in text and "list_games" in text


def test_protocol_errors(app, duo):
    _, key, _ = duo[0]
    assert rpc(app, key, "nope/nothing").json()["error"]["code"] == -32601
    assert rpc(app, key, "tools/call", {"name": "nope"}).json()["error"]["code"] == -32602
    bad = plain(app).post("/mcp", content=b"{not json", headers={"Authorization": f"Bearer {key}"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == -32700
    assert plain(app).get("/mcp").status_code == 405
    batch = plain(app).post(
        "/mcp",
        json=[{"jsonrpc": "2.0", "id": i, "method": "ping"} for i in (1, 2)],
        headers={"Authorization": f"Bearer {key}"},
    )
    assert batch.json()["error"]["code"] == -32600  # batches are not supported


def test_bad_tool_arguments_are_tool_errors(app, duo):
    _, key, _ = duo[0]
    is_error, text = call(app, key, "review_game")
    assert is_error and "Bad arguments" in text
    assert call(app, key, "list_games", nope=1)[0] is True


# ------------------------------------------------------------------ tools


def test_get_profile(app, duo):
    (ca, key, _), (_cb, _, _) = duo
    ca.post("/api/puzzles/p00/attempt", json={"solved": True})  # fork + pin
    ca.post("/api/puzzles/p01/attempt", json={"solved": False})  # mateIn2, adds a card
    ca.post("/api/lessons/test/positions/0")
    is_error, p = call(app, key, "get_profile")
    assert not is_error
    assert p["games"]["count"] == 1 and p["games"]["average_plies"] == 5
    (grp,) = p["games"]["by_color_and_level"]
    assert (grp["color"], grp["level"], grp["wins"]) == ("white", 800, 1)
    (op,) = p["openings_played"]
    assert (op["family"], op["key"], op["color"], op["games"]) == (
        "Italian Game",
        "Italian_Game",
        "white",
        1,
    )
    assert p["mistakes_deck"]["total"] == 1 and p["mistakes_deck"]["by_motif"] == {"mateIn2": 1}
    themes = {t["key"]: t for t in p["puzzles"]["themes_weakest_first"]}
    assert themes["fork"]["solved"] == 1 and themes["fork"]["attempts"] == 1
    assert themes["mateIn2"]["solved"] == 0
    ratings = [t["rating"] for t in p["puzzles"]["themes_weakest_first"]]
    assert ratings == sorted(ratings)
    assert [x["slug"] for x in p["lessons"]["done"]] == ["test"] and not p["lessons"]["not_done"]
    valid = p["valid_values_for_save_plan"]
    assert {"key": "fork", "name": "Вилка"} in valid["themes"]
    assert [x["slug"] for x in valid["lessons"]] == ["test"]
    assert "Italian_Game" in [o["key"] for o in valid["openings"]]
    assert p["plan"] is None
    act = p["activity"]
    assert act["week"] == {"goal": 3, "active_days": 1, "met": False, "streak_weeks": 0}
    today = local_today(now_utc(), server_tz()).isoformat()
    assert act["last_active_date"] == today and act["active_days_last_28"] == 1
    # Only the stored achievements: the met ones count after the app awards them.
    assert act["achievements_earned"] == []
    assert sql(app.state.settings, "SELECT COUNT(*) FROM achievements") == [(0,)]  # read only
    assert ca.get("/api/achievements").status_code == 200  # the app awards them
    titles = call(app, key, "get_profile")[1]["activity"]["achievements_earned"]
    assert titles == ["Первая задача", "Первый урок", "Первая партия"]
    assert "Queen" not in json.dumps(p)  # bob's opening


def test_list_games_sees_only_own_games(app, duo):
    (_, key_a, ga), (_, key_b, gb) = duo
    ok, games = call(app, key_a, "list_games", limit=5)
    assert not ok and [g["id"] for g in games] == [ga]
    assert games[0]["opening"] == "Итальянская партия" or "Italian" in games[0]["opening"]
    assert (games[0]["color"], games[0]["level"], games[0]["plies"]) == ("white", 800, 5)
    _, theirs = call(app, key_b, "list_games")
    assert [g["id"] for g in theirs] == [gb] and ga != gb


def test_training_games_in_mcp(app, duo):
    (ca, key, normal), _b = duo

    def save(pgn, color, result, takebacks=0, hints=0):
        game = {"pgn": pgn, "player_color": color, "level": 800, "result": result}
        return ca.post("/api/games", json={**game, "takebacks": takebacks, "hints": hints}).json()[
            "id"
        ]

    training = save(QGD, "white", "1-0", takebacks=2, hints=1)
    black_win = save(ITALIAN, "black", "0-1", hints=1)
    unfinished = save(ITALIAN, "black", "*", takebacks=1)
    _, games = call(app, key, "list_games")
    fields = {g["id"]: (g["training"], g["takebacks"], g["hints"]) for g in games}
    assert fields == {
        training: (True, 2, 1),
        black_win: (True, 0, 1),
        unfinished: (True, 1, 0),
        normal: (False, 0, 0),
    }
    _, p = call(app, key, "get_profile")
    # count keeps all games; training counts only finished training games
    assert (p["games"]["count"], p["games"]["training"]) == (4, 2)
    (grp,) = p["games"]["by_color_and_level"]  # the training wins do not count
    assert (grp["color"], grp["level"], grp["games"], grp["wins"]) == ("white", 800, 1, 1)
    # training games stay in the repertoire, but their results do not count
    played = {
        (o["family"], o["color"]): (o["games"], o["wins"], o["losses"], o["draws"], o["training"])
        for o in p["openings_played"]
    }
    assert played == {
        ("Italian Game", "white"): (1, 1, 0, 0, 0),
        ("Queens Gambit Declined", "white"): (1, 0, 0, 0, 1),
        ("Italian Game", "black"): (2, 0, 0, 0, 1),
    }
    app.state.pool = FakePool()
    is_error, rev = call(app, key, "review_game", game_id=training)
    assert not is_error, rev
    assert (rev["training"], rev["takebacks"], rev["hints"]) == (True, 2, 1)
    is_error, rev = call(app, key, "review_game", game_id=normal)
    assert not is_error, rev
    assert (rev["training"], rev["takebacks"], rev["hints"]) == (False, 0, 0)


def test_weekly_review_tells_about_training_games(app, duo):
    _, key, _ = duo[0]
    text = rpc(app, key, "prompts/get", {"name": "weekly_review"}).json()["result"]["messages"]
    assert "training: true" in text[0]["content"]["text"]


def test_review_of_another_users_game_is_an_error(app, duo):
    (_, key_a, _), (_, _, gb) = duo
    app.state.pool = FakePool()
    is_error, text = call(app, key_a, "review_game", game_id=gb)
    assert is_error and "not found" in text
    assert app.state.pool.calls == []  # the engine was never asked
    assert call(app, key_a, "review_game", game_id=99999)[0] is True


def test_analyse_position_clamps_depth_and_checks_fen(app, duo):
    _, key, _ = duo[0]
    app.state.pool = FakePool()
    ok, data = call(app, key, "analyse_position", fen=START, depth=99)
    assert not ok and data["depth"] == 18 and len(data["lines"]) == 3
    assert data["lines"][0]["in_words"] and data["turn"] == "white"
    assert app.state.pool.calls == [(START, 18, 3)]
    assert call(app, key, "analyse_position", fen="garbage")[0] is True
    assert call(app, key, "analyse_position", fen="8/8/8/8/8/8/8/8 w - - 0 1")[0] is True
    mated = "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3"
    assert call(app, key, "analyse_position", fen=mated)[1]["game_over"] == "0-1"


def test_heavy_tool_waits_for_a_slot(app, duo):
    _, key, _ = duo[0]
    app.state.pool = FakePool()
    app.state.engine_slots.wait_s = 0.05
    (user_id,) = [
        r[0]
        for r in sqlite3.connect(app.state.settings.app_db_path).execute(
            "SELECT id FROM users WHERE login = 'alice'"
        )
    ]
    for _i in range(app.state.engine_slots.limit):
        assert app.state.engine_slots.acquire(user_id)
    is_error, text = call(app, key, "analyse_position", fen=START)
    assert is_error and "тренер" in text


def test_eval_words():
    assert _eval_words(5, None) == "позиция примерно равная"
    assert "белых" in _eval_words(150, None) and "чёрных" in _eval_words(-500, None)
    assert _eval_words(None, 2) == "у белых мат в 2" and _eval_words(None, -3).endswith("в 3")


# ------------------------------------------------------------------ plan


PLAN = {
    "summary": "Больше задач на вилки и итальянская партия.",
    "focus_themes": ["fork"],
    "lessons": ["test"],
    "openings": ["Italian_Game"],
}


def test_save_and_read_plan(app, duo):
    (ca, key_a, _), (cb, key_b, _) = duo
    assert call(app, key_a, "get_plan")[1] == {"plan": None}
    assert ca.get("/api/plan").json() == {"plan": None}
    ok, saved = call(app, key_a, "save_plan", **PLAN)
    assert not ok and saved["plan"]["focus_themes"] == ["fork"] and saved["plan"]["created_at"]
    expected = {"created_at": saved["plan"]["created_at"], **PLAN}
    assert ca.get("/api/plan").json() == {"plan": expected}
    assert call(app, key_a, "get_plan")[1] == {"plan": expected}
    # user B sees nothing of it, by key and by cookie
    assert call(app, key_b, "get_plan")[1] == {"plan": None}
    assert cb.get("/api/plan").json() == {"plan": None}
    assert call(app, key_a, "get_profile")[1]["plan"] == expected


def test_new_plan_replaces_the_old_one_and_history_stays(app, duo, mcfg):
    (ca, key, _), _b = duo
    call(app, key, "save_plan", **PLAN)
    call(app, key, "save_plan", **{**PLAN, "summary": "Второй план", "openings": []})
    assert ca.get("/api/plan").json()["plan"]["summary"] == "Второй план"
    assert sql(mcfg, "SELECT COUNT(*) FROM plans")[0][0] == 2


@pytest.mark.parametrize(
    ("change", "needle"),
    [
        ({"focus_themes": ["nope"]}, "Allowed values"),
        ({"lessons": ["nope"]}, '"test"'),
        ({"openings": ["Nope_Opening"]}, "Italian_Game"),
        ({"focus_themes": ["fork", "pin", "skewer", "mate"]}, "at most 3"),
        ({"lessons": ["test"] * 7 + ["x"]}, "unknown values"),
        ({"summary": "x" * 1501}, "1500"),
        ({"summary": "  "}, "non-empty"),
        ({"focus_themes": "fork"}, "list of strings"),
    ],
)
def test_save_plan_rejects_bad_values(app, duo, mcfg, change, needle):
    _, key, _ = duo[0]
    is_error, text = call(app, key, "save_plan", **{**PLAN, **change})
    assert is_error and needle in text
    assert sql(mcfg, "SELECT COUNT(*) FROM plans")[0][0] == 0


def test_tool_error_type():
    assert issubclass(ToolError, Exception)


# ------------------------------------------------------------------ real engine


@pytest.mark.engine
def test_engine_tools(app, duo):
    # the coach facts link real lesson slugs, so this test reads the real lessons
    app.state.settings = replace(app.state.settings, lessons_dir=default_settings.lessons_dir)
    (ca, key, _), _b = duo
    gid = ca.post(
        "/api/games", json={"pgn": MATE, "player_color": "black", "result": "1-0"}
    ).json()["id"]
    with TestClient(app):  # runs the lifespan, so the pool is closed at the end
        ok, data = call(app, key, "analyse_position", fen=START, depth=10)
        assert not ok and len(data["lines"]) == 3 and data["lines"][0]["pv"]
        ok, rev = call(app, key, "review_game", game_id=gid)
        assert not ok, rev
        assert rev["side"] == "black"
        moment = next(m for m in rev["key_moments"] if m["san"] == "Nf6")
        assert moment["classification"] == "blunder" and moment["explanation"]
        assert any(b["san"] == "Nf6" for b in rev["bad_moves"])
    # review by tool does not touch the mistakes deck
    assert call(app, key, "get_profile")[1]["mistakes_deck"]["total"] == 0


# ------------------------------------------------------------------ review fixes


def test_batch_is_rejected(app, duo):
    _, key, _ = duo[0]
    batch = [{"jsonrpc": "2.0", "id": 1, "method": "ping"}] * 3
    r = plain(app).post("/mcp", json=batch, headers={"Authorization": f"Bearer {key}"})
    assert r.json()["error"]["code"] == -32600
    assert "Batch" in r.json()["error"]["message"]


def _fill_slots(app, name="alice"):
    app.state.engine_slots.wait_s = 0.05
    (user_id,) = [
        r[0]
        for r in sqlite3.connect(app.state.settings.app_db_path).execute(
            "SELECT id FROM users WHERE login = ?", (name,)
        )
    ]
    for _i in range(app.state.engine_slots.limit):
        assert app.state.engine_slots.acquire(user_id)


@pytest.mark.parametrize("tool", ["get_profile", "list_games"])
def test_profile_and_games_take_an_engine_slot(app, duo, tool):
    _, key, _ = duo[0]
    _fill_slots(app)
    is_error, text = call(app, key, tool)
    assert is_error and "тренер" in text


def test_analyse_position_passes_a_time_limit(app, duo):
    _, key, _ = duo[0]
    app.state.pool = FakePool()
    assert not call(app, key, "analyse_position", fen=START)[0]
    assert app.state.pool.movetimes == [3000]


def test_only_the_newest_20_plans_stay(app, duo, mcfg):
    _, key, _ = duo[0]
    for i in range(23):
        assert not call(app, key, "save_plan", **{**PLAN, "summary": f"план {i}"})[0]
    assert sql(mcfg, "SELECT COUNT(*) FROM plans")[0][0] == 20
    assert call(app, key, "get_plan")[1]["plan"]["summary"] == "план 22"


def test_bad_mcp_key_does_not_lock_the_browser_login(app, duo):
    for _i in range(6):
        rpc(app, "wrong-key", "ping")
    assert rpc(app, "wrong-key", "ping").status_code == 429
    r = plain(app).post("/api/auth/login", json={"login": "alice", "token": "wrong"})
    assert r.status_code != 429


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("list_games", {"limit": "5"}),
        ("list_games", {"limit": [1]}),
        ("review_game", {"game_id": 2**70}),
        ("review_game", {"game_id": [1]}),
        ("review_game", {"game_id": True}),
        ("analyse_position", {"fen": ["x"]}),
        ("analyse_position", {"fen": "x" * 500}),
        ("analyse_position", {"fen": START, "depth": "9"}),
        ("save_plan", {"summary": ["x"], "focus_themes": [], "lessons": [], "openings": []}),
    ],
)
def test_bad_argument_types_are_tool_errors(app, duo, name, args):
    _, key, _ = duo[0]
    app.state.pool = FakePool()
    assert call(app, key, name, **args)[0] is True


@pytest.mark.parametrize("params", [{"name": ["x"]}, {"name": {"a": 1}}, {"name": 5}])
def test_bad_tool_name_is_a_rpc_error(app, duo, params):
    _, key, _ = duo[0]
    r = rpc(app, key, "tools/call", params)
    assert r.status_code == 200 and r.json()["error"]["code"] == -32602


@pytest.mark.parametrize(
    "args",
    [
        '{"name": "list_games", "arguments": {"limit": Infinity}}',
        '{"name": "analyse_position", "arguments": {"fen": "x", "depth": -Infinity}}',
    ],
)
def test_infinity_is_a_tool_error_not_a_500(app, duo, args):
    _, key, _ = duo[0]
    raw = '{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": ' + args + "}"
    r = plain(app).post(
        "/mcp",
        content=raw.encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    assert r.status_code == 200 and r.json()["result"]["isError"] is True
