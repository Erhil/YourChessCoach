import threading
from dataclasses import replace

import pytest
from conftest import TEST_LOGIN
from fastapi.testclient import TestClient
from test_auth import LESSON

from app.activity.achievements import CATALOGUE, award, mark_seen
from app.auth import service
from app.config import settings as default_settings
from app.db import connect
from app.main import create_app

NOW = "2026-10-21T12:00:00Z"  # Wednesday; its week starts on Monday 2026-10-19
TODAY = "2026-10-21T10:00:00Z"
PUZZLE = (
    "INSERT INTO puzzle_attempts (user_id, puzzle_id, created_at, solved, used_hint,"
    " puzzle_rating, rating_before, rating_after) VALUES (?, 'p', ?, ?, 0, 800, 800, 810)"
)
GAME = (
    "INSERT INTO games (user_id, player_color, level, result, termination, pgn, moves_count,"
    " blunders) VALUES (?, ?, ?, ?, ?, '1. e4 *', ?, ?)"
)
CARD = (
    "INSERT INTO mistakes (user_id, source, ref, fen, best_uci, best_san, created_at, due_at,"
    " reviews, lapses, learned_at) VALUES (?, 'puzzle', ?, 'f', 'e2e4', 'e4', ?, ?, 0, 0, ?)"
)
RATING = "INSERT INTO user_ratings (user_id, scope, rating, attempts) VALUES (?, ?, ?, ?)"


@pytest.fixture
def client(tmp_path, monkeypatch):
    for module in ("routes", "achievements"):
        monkeypatch.setattr(f"app.activity.{module}.now_utc", lambda: NOW)
    lessons = tmp_path / "lessons"
    lessons.mkdir()
    for i in range(1, 6):
        (lessons / f"0{i}-l{i}.md").write_text(LESSON, encoding="utf-8")
    settings = replace(
        default_settings,
        app_db_path=tmp_path / "app.db",
        frontend_dist=tmp_path / "dist",
        lessons_dir=lessons,
    )
    with TestClient(create_app(settings)) as c:
        c.db = connect(settings.app_db_path)
        c.user = c.db.execute("SELECT id FROM users WHERE login = ?", (TEST_LOGIN,)).fetchone()[0]
        c.other = service.create_user(c.db, "other", "zzzz-zzzz-zzzz-zzzz")
        c.lessons = lessons
        yield c
        c.db.close()


def run(client, sql, *rows):
    with client.db:
        client.db.executemany(sql, rows)


def puzzles(client, n, solved=1, user=None, at=TODAY):
    run(client, PUZZLE, *[(user or client.user, at, solved)] * n)


def cards(client, n, learned=True):
    run(
        client,
        CARD,
        *[
            (client.user, f"{learned}{i}", TODAY, TODAY, TODAY if learned else None)
            for i in range(n)
        ],
    )


def got(client) -> dict:
    r = client.get("/api/achievements", params={"tz": 0})
    assert r.status_code == 200, r.text
    return r.json()


def earned(client) -> set[str]:
    return {a["key"] for a in got(client)["earned"]}


def test_total_is_the_catalogue_size(client):
    # The profile tile shows «N из total».
    assert got(client)["total"] == 16


def test_puzzle_counts(client):
    puzzles(client, 5, solved=0)
    assert earned(client) == set()
    puzzles(client, 24)
    assert earned(client) == {"first_puzzle"}
    puzzles(client, 1)
    assert earned(client) == {"first_puzzle", "puzzles_25"}
    puzzles(client, 74)
    assert "puzzles_100" not in earned(client)
    puzzles(client, 1)
    assert "puzzles_100" in earned(client)


def test_lessons(client):
    def solve(slug):
        run(
            client,
            "INSERT INTO lesson_progress (user_id, slug, position) VALUES (?, ?, 0)",
            (client.user, slug),
        )

    assert earned(client) == set()
    for i in range(1, 5):
        solve(f"l{i}")
    assert earned(client) == {"first_lesson"}
    solve("l5")
    assert earned(client) == {"first_lesson", "lessons_5"}


@pytest.mark.parametrize(
    "game, keys",
    [
        (("white", 1100, "*", None, 40, 0), set()),
        (("white", 1100, "1/2-1/2", None, 10, None), {"first_game"}),  # a draw is not a win
        (("white", 1000, "1-0", None, 10, None), {"first_game"}),
        (("black", 1100, "0-1", None, 10, None), {"first_game", "win_1100"}),
        (("white", 1100, "0-1", None, 10, None), {"first_game"}),
        (("white", 800, "1-0", "checkmate", 10, None), {"first_game", "mate"}),
        (("black", 800, "1-0", "checkmate", 10, None), {"first_game"}),  # mated, not mating
        (("white", 800, "1/2-1/2", None, 39, 0), {"first_game", "clean_game"}),  # 20 own moves
        (("white", 800, "1/2-1/2", None, 38, 0), {"first_game"}),  # 19 own moves
        (("black", 800, "1/2-1/2", None, 40, 0), {"first_game", "clean_game"}),
        (("black", 800, "1/2-1/2", None, 39, 0), {"first_game"}),
        (("white", 800, "1/2-1/2", None, 40, None), {"first_game"}),  # blunders unknown
        (("white", 800, "1/2-1/2", None, 40, 1), {"first_game"}),
    ],
)
def test_games(client, game, keys):
    run(client, GAME, (client.user, *game))
    assert earned(client) == keys


@pytest.mark.parametrize(
    "game",
    [
        ("black", 1100, "0-1", None, 10, None),  # win_1100
        ("white", 800, "1-0", "checkmate", 10, None),  # mate
        ("white", 800, "1/2-1/2", None, 40, 0),  # clean_game
    ],
)
@pytest.mark.parametrize("takebacks, hints", [(1, 0), (0, 1)])
def test_training_game_gives_only_first_game(client, game, takebacks, hints):
    run(
        client,
        GAME.replace("blunders)", "blunders, takebacks, hints)").replace("?)", "?, ?, ?)"),
        (client.user, *game, takebacks, hints),
    )
    assert earned(client) == {"first_game"}


def test_cards(client):
    cards(client, 3, learned=False)
    assert earned(client) == set()
    cards(client, 9)
    assert earned(client) == {"first_card"}
    run(client, CARD, (client.user, "last", TODAY, TODAY, TODAY))
    assert earned(client) == {"first_card", "cards_10"}


def test_themes_and_kept_after_a_drop(client):
    run(client, RATING, (client.user, "fork", 699.0, 9), (client.user, "short", 900.0, 30))
    assert earned(client) == set()  # "short" is not an offered theme
    with client.db:
        client.db.execute(
            "UPDATE user_ratings SET rating = 700, attempts = 10 WHERE scope = 'fork'"
        )
    assert earned(client) == {"theme_10", "theme_plus_100"}
    with client.db:
        client.db.execute("UPDATE user_ratings SET rating = 550 WHERE scope = 'fork'")
    assert earned(client) == {"theme_10", "theme_plus_100"}


def days_of_weeks(weeks_back, days=3):
    # Mondays: 2026-10-19 is the current week.
    mondays = ["2026-10-19", "2026-10-12", "2026-10-05", "2026-09-28"]
    return [
        f"{m[:8]}{int(m[8:]) + d:02d}T10:00:00Z" for m in mondays[:weeks_back] for d in range(days)
    ]


def test_week_goal_and_four_weeks(client):
    for ts in days_of_weeks(4, days=2):  # 2 of 3 days: no week is met
        puzzles(client, 1, solved=0, at=ts)
    assert earned(client) == set()
    for ts in days_of_weeks(3):  # 3 weeks met: the current one and two past ones
        puzzles(client, 1, solved=0, at=ts)
    assert earned(client) == {"week_goal"}
    for ts in days_of_weeks(4):
        puzzles(client, 1, solved=0, at=ts)
    assert earned(client) == {"week_goal", "weeks_4"}


def test_past_week_alone_gives_week_goal(client):
    for ts in ["2026-10-12T10:00:00Z", "2026-10-13T10:00:00Z", "2026-10-14T10:00:00Z"]:
        puzzles(client, 1, solved=0, at=ts)
    assert earned(client) == {"week_goal"}


def test_comeback_needs_activity_today(client):
    puzzles(client, 1, solved=0, at="2026-10-17T10:00:00Z")  # 3 whole days without activity
    assert earned(client) == set()
    puzzles(client, 1, solved=0)
    assert earned(client) == {"comeback"}


def test_no_comeback_without_a_gap(client):
    puzzles(client, 1, solved=0, at="2026-10-18T10:00:00Z")  # only 2 days without activity
    puzzles(client, 1, solved=0)
    assert earned(client) == set()


def test_awarded_once_and_seen(client):
    puzzles(client, 1)
    first = client.get("/api/activity", params={"tz": 0}).json()["achievements"]
    assert set(first) == {"new", "next"}
    assert first["new"] == [
        {
            "key": "first_puzzle",
            "title": "Первая задача",
            "text": "Вы решили первую задачу.",
            "earned_at": NOW,
        }
    ]
    again = client.get("/api/activity", params={"tz": 0}).json()["achievements"]
    assert again["new"] == first["new"]
    assert client.post("/api/achievements/seen", json={"keys": ["first_puzzle"]}).status_code == 204
    assert client.get("/api/activity", params={"tz": 0}).json()["achievements"]["new"] == []
    assert got(client)["earned"] == first["new"]
    rows = client.db.execute("SELECT COUNT(*) FROM achievements WHERE user_id = ?", (client.user,))
    assert rows.fetchone()[0] == 1


def test_parallel_awards_insert_once(client):
    puzzles(client, 25)
    path = client.app.state.settings.app_db_path
    barrier = threading.Barrier(4)
    errors = []

    results = []

    def worker():
        db = connect(path)
        try:
            barrier.wait()
            results.append(award(db, client.lessons, client.user, 0))
        except Exception as e:  # noqa: BLE001 - the test reports it below
            errors.append(e)
        finally:
            db.close()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    rows = client.db.execute(
        "SELECT key, COUNT(*) FROM achievements WHERE user_id = ? GROUP BY key", (client.user,)
    ).fetchall()
    assert {r[0]: r[1] for r in rows} == {"first_puzzle": 1, "puzzles_25": 1}
    # Every response sees the two stored keys with the same earned_at. Until `seen`, the same
    # key is "new" in all parallel responses: the client shows it once and marks it seen.
    assert len(results) == 4
    stored = dict(client.db.execute("SELECT key, earned_at FROM achievements").fetchall())
    for data in results:
        assert {a["key"]: a["earned_at"] for a in data["earned"]} == stored
        assert [a["key"] for a in data["new"]] == ["first_puzzle", "puzzles_25"]


def test_next(client):
    data = got(client)
    assert [a["key"] for a in data["next"]] == ["first_puzzle", "first_lesson", "first_game"]
    assert data["next"][0] == {
        "key": "first_puzzle",
        "title": "Первая задача",
        "text": "Решите первую задачу.",
        "unit": "задач",
        "progress": 0,
        "target": 1,
    }
    puzzles(client, 24)
    cards(client, 1)
    run(client, RATING, (client.user, "fork", 650.0, 5))
    nxt = got(client)["next"]
    # 24/25, then 5/10 and 50/100: the catalogue order breaks the tie.
    assert [(a["key"], a["progress"], a["target"]) for a in nxt] == [
        ("puzzles_25", 24, 25),
        ("theme_10", 5, 10),
        ("theme_plus_100", 50, 100),
    ]


def test_next_never_has_hidden_or_earned(client):
    hidden = {"comeback"}
    puzzles(client, 1, solved=0, at="2026-10-10T10:00:00Z")
    for n in (1, 30, 100):
        puzzles(client, n)
        data = got(client)
        keys = {a["key"] for a in data["next"]}
        assert len(data["next"]) <= 3 and not keys & hidden
        assert not keys & {a["key"] for a in data["earned"]}
    assert len(CATALOGUE) == 16


def test_next_text_is_the_goal_and_earned_text_stays(client):
    puzzles(client, 1)  # first_puzzle is earned; its text states the result
    data = got(client)
    assert data["earned"][0]["text"] == "Вы решили первую задачу."
    nxt = {a["key"]: a["text"] for a in data["next"]}
    assert nxt["puzzles_25"] == "Решите 25 задач."
    assert "week_goal" not in nxt


def test_puzzles_25_earned_text(client):
    puzzles(client, 25)
    texts = {a["key"]: a["text"] for a in got(client)["earned"]}
    assert texts["puzzles_25"] == "Вы решили 25 задач."


def test_next_unit_of_every_goal():
    units = {key: unit for key, _, _, goal, _, _, unit in CATALOGUE if goal is not None}
    assert units == {
        **dict.fromkeys(["first_puzzle", "puzzles_25", "puzzles_100", "theme_10"], "задач"),
        **dict.fromkeys(["first_lesson", "lessons_5"], "уроков"),
        **dict.fromkeys(["first_card", "cards_10"], "карточек"),
        "theme_plus_100": "очков рейтинга",
        "weeks_4": "недель",
        **dict.fromkeys(["first_game", "win_1100", "mate", "clean_game"], "партий"),
    }


def test_next_has_the_unit(client):
    puzzles(client, 24)
    run(client, RATING, (client.user, "fork", 650.0, 5))
    nxt = {a["key"]: a["unit"] for a in got(client)["next"]}
    assert nxt == {"puzzles_25": "задач", "theme_10": "задач", "theme_plus_100": "очков рейтинга"}


def test_seen_validation(client):
    assert client.post("/api/achievements/seen", json={"keys": ["x"] * 51}).status_code == 422
    assert client.post("/api/achievements/seen", json={"keys": "first_puzzle"}).status_code == 422
    assert client.post("/api/achievements/seen", json={"keys": ["x"] * 50}).status_code == 204


def test_other_users_data_does_not_count(client):
    puzzles(client, 30, user=client.other)
    run(client, GAME, (client.other, "white", 1500, "1-0", "checkmate", 60, 0))
    assert earned(client) == set()
    award(client.db, client.lessons, client.other, 0)
    puzzles(client, 1)
    assert earned(client) == {"first_puzzle"}
    # The other user marks his own achievement as seen; ours stays new.
    mark_seen(client.db, client.other, ["first_puzzle"])
    new = client.get("/api/activity", params={"tz": 0}).json()["achievements"]["new"]
    assert [a["key"] for a in new] == ["first_puzzle"]


def test_award_writes_only_new_keys(client):
    puzzles(client, 1)
    got(client)  # stores first_puzzle
    sql = []
    client.db.set_trace_callback(sql.append)
    try:
        award(client.db, client.lessons, client.user, 0)  # nothing new: no write
        assert not [q for q in sql if "INSERT" in q or q.startswith("BEGIN")]
        run(
            client,
            "INSERT INTO lesson_progress (user_id, slug, position) VALUES (?, 'l1', 0)",
            (client.user,),
        )
        award(client.db, client.lessons, client.user, 0)
    finally:
        client.db.set_trace_callback(None)
    inserts = [q for q in sql if "INSERT" in q and "achievements" in q]
    assert len(inserts) == 1 and "first_lesson" in inserts[0] and "first_puzzle" not in inserts[0]


def test_theme_gain_uses_the_raw_rating(client):
    run(client, RATING, (client.user, "fork", 699.6, 3))  # rounds to 700, but the gain is 99.6
    assert earned(client) == set()
    gain = next(a for a in got(client)["next"] if a["key"] == "theme_plus_100")
    assert (gain["progress"], gain["target"]) == (99, 100)
    with client.db:
        client.db.execute("UPDATE user_ratings SET rating = 700.0 WHERE scope = 'fork'")
    assert earned(client) == {"theme_plus_100"}


def test_week_goal_not_in_next_but_awarded(client):
    # 2 of 3 days: week_goal is near, but the week block shows it, not `next`.
    for ts in ["2026-10-19T10:00:00Z", "2026-10-20T10:00:00Z"]:
        puzzles(client, 1, solved=0, at=ts)
    data = got(client)
    assert "week_goal" not in {a["key"] for a in data["next"]}
    assert "week_goal" not in {a["key"] for a in data["earned"]}
    puzzles(client, 1, solved=0)  # the third day of the week: the goal is met
    assert "week_goal" in earned(client)
    new = client.get("/api/activity", params={"tz": 0}).json()["achievements"]
    assert "week_goal" in {a["key"] for a in new["new"]}
    assert "week_goal" not in {a["key"] for a in new["next"]}


def test_weeks_4_progress_is_streak_weeks(client):
    for ts in days_of_weeks(3):
        puzzles(client, 1, solved=0, at=ts)
    data = got(client)
    assert {a["key"] for a in data["earned"]} == {"week_goal"}
    nxt = {a["key"]: (a["progress"], a["target"]) for a in data["next"]}
    assert nxt["weeks_4"] == (3, 4)


def test_activity_reads_event_counts_once(client, monkeypatch):
    from app.activity import days

    calls = []
    real = days.event_counts
    monkeypatch.setattr(days, "event_counts", lambda *a: calls.append(1) or real(*a))
    puzzles(client, 1)
    assert client.get("/api/activity", params={"tz": 0}).status_code == 200
    assert len(calls) == 1
