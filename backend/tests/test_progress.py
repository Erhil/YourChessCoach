from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.config import settings as default_settings
from app.db import connect
from app.main import create_app

# Wednesday; its week starts on Monday 2026-10-19.
NOW = "2026-10-21T12:00:00Z"

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
def db_path(tmp_path):
    return tmp_path / "app.db"


@pytest.fixture
def client(tmp_path, db_path):
    lessons = tmp_path / "lessons"
    lessons.mkdir()
    (lessons / "01-a.md").write_text(LESSON, encoding="utf-8")
    (lessons / "02-b.md").write_text(LESSON, encoding="utf-8")
    settings = replace(
        default_settings, app_db_path=db_path, frontend_dist=tmp_path / "dist", lessons_dir=lessons
    )
    with TestClient(create_app(settings)) as c:
        yield c


def run(db_path, sql, rows):
    conn = connect(db_path)
    with conn:
        conn.executemany(sql, rows)
    conn.close()


def test_empty_database(client):
    data = client.get("/api/progress").json()
    assert data.pop("calendar") == [] and len(data.pop("weeks")) == 8
    assert data == {
        "puzzles": {"rating": 600, "attempts": 0, "solved": 0, "history": []},
        "themes": [],
        "weak_theme": None,
        "games": {
            "count": 0,
            "wins": 0,
            "losses": 0,
            "draws": 0,
            "training": 0,
            "player_moves": 0,
            "blunders": 0,
            "blunders_per_10_moves": 0.0,
        },
        "lessons": {"completed": 0, "total": 2},
        "mistakes": {"total": 0, "due": 0, "learned": 0},
    }


def test_numbers_after_inserts(client, db_path):
    client.get("/api/progress")
    run(
        db_path,
        "INSERT INTO games (user_id, player_color, result, moves_count, pgn)"
        " VALUES ((SELECT MIN(id) FROM users), ?, ?, ?, 'x')",
        [("white", "1-0", 41), ("black", "1-0", 40), ("black", "1/2-1/2", 10), ("white", "*", 3)],
    )
    run(
        db_path,
        "INSERT INTO puzzle_attempts (user_id, puzzle_id, created_at, solved, used_hint,"
        " puzzle_rating, rating_before, rating_after)"
        " VALUES ((SELECT MIN(id) FROM users), ?, ?, ?, 0, 700, 600, ?)",
        [("a", "2026-01-01T00:00:00Z", 1, 620.4), ("b", "2026-01-02T00:00:00Z", 0, 610.0)],
    )
    run(
        db_path,
        "INSERT INTO mistakes (user_id, source, ref, fen, best_uci, best_san, classification,"
        " created_at, due_at, reviews, lapses)"
        " VALUES ((SELECT MIN(id) FROM users), ?, ?, 'f', 'e2e4', 'e4', ?, 'n', ?, 0, 0)",
        [
            ("game", "1", "blunder", "2000-01-01T00:00:00Z"),
            ("play", "2", "blunder", "2999-01-01T00:00:00Z"),
            ("puzzle", "3", None, "2999-01-01T00:00:00Z"),
            ("game", "4", "mistake", "2999-01-01T00:00:00Z"),
        ],
    )
    run(
        db_path,
        "INSERT INTO lesson_progress (user_id, slug, position)"
        " VALUES ((SELECT MIN(id) FROM users), ?, 1)",
        [("a",)],
    )
    run(
        db_path,
        "INSERT INTO user_ratings (user_id, scope, rating, attempts)"
        " VALUES ((SELECT MIN(id) FROM users), ?, ?, ?)",
        [("overall", 610.0, 2)],
    )
    data = client.get("/api/progress").json()
    assert data["puzzles"] == {
        "rating": 610,
        "attempts": 2,
        "solved": 1,
        "history": [
            {"at": "2026-01-01T00:00:00Z", "rating": 620},
            {"at": "2026-01-02T00:00:00Z", "rating": 610},
        ],
    }
    # white 41 plies -> 21 moves, black 40 -> 20, black 10 -> 5, white 3 -> 2
    assert data["games"] == {
        "count": 4,
        "wins": 1,
        "losses": 1,
        "draws": 1,
        "training": 0,
        "player_moves": 48,
        "blunders": 2,
        "blunders_per_10_moves": 0.42,
    }
    assert data["lessons"] == {"completed": 1, "total": 2}
    assert data["mistakes"] == {"total": 4, "due": 1, "learned": 0}


def test_training_games_do_not_count_in_results(client, db_path):
    run(
        db_path,
        "INSERT INTO games (user_id, player_color, result, moves_count, pgn, takebacks, hints)"
        " VALUES ((SELECT MIN(id) FROM users), ?, ?, ?, 'x', ?, ?)",
        [
            ("white", "1-0", 41, 0, 0),
            ("white", "1-0", 41, 1, 0),
            ("black", "1-0", 40, 0, 2),
            ("black", "1/2-1/2", 10, 3, 3),
            ("white", "*", 3, 1, 0),
            ("black", "0-1", 40, 0, 1),
        ],
    )
    games = client.get("/api/progress").json()["games"]
    # 21 + 21 + 20 + 5 + 2 + 20 own moves: the move count and the blunder rate keep training games
    # training: only finished training games, as the win, draw and loss buckets
    assert {k: games[k] for k in ("count", "wins", "losses", "draws", "training")} == {
        "count": 6,
        "wins": 1,
        "losses": 0,
        "draws": 0,
        "training": 4,
    }
    assert games["player_moves"] == 89


def test_themes_weakest_first_and_weak_theme_needs_three_attempts(client, db_path):
    client.get("/api/progress")
    run(
        db_path,
        "INSERT INTO user_ratings (user_id, scope, rating, attempts)"
        " VALUES ((SELECT MIN(id) FROM users), ?, ?, ?)",
        [
            ("overall", 600.0, 9),
            ("fork", 700.0, 5),
            ("pin", 500.0, 2),
            ("skewer", 650.0, 3),
            ("short", 100.0, 4),
        ],
    )
    data = client.get("/api/progress").json()
    assert [t["key"] for t in data["themes"]] == ["pin", "skewer", "fork"]
    assert data["themes"][0] == {"key": "pin", "name": "Связка", "rating": 500, "attempts": 2}
    assert data["weak_theme"] == {"key": "skewer", "name": "Линейный удар"}


@pytest.fixture
def weekly(client, monkeypatch):
    monkeypatch.setattr("app.progress.routes.now_utc", lambda: NOW)
    client.get("/api/progress")
    return client


def attempts(db_path, rows):
    run(
        db_path,
        "INSERT INTO puzzle_attempts (user_id, puzzle_id, created_at, solved, used_hint,"
        " puzzle_rating, rating_before, rating_after)"
        " VALUES ((SELECT MIN(id) FROM users), 'p', ?, ?, 0, 700, ?, ?)",
        rows,
    )


def test_calendar_range_and_local_day(weekly, db_path):
    attempts(
        db_path,
        [
            # 23:00Z on Sunday 08-02 is Monday 08-03 in Moscow: the first day of the 12 weeks.
            ("2026-08-02T23:00:00Z", 1, 600, 600),
            ("2026-10-20T22:30:00Z", 1, 600, 600),
            ("2026-10-20T22:40:00Z", 1, 600, 600),
            # Tomorrow in Moscow, today in UTC.
            ("2026-10-21T22:00:00Z", 1, 600, 600),
        ],
    )
    moscow = weekly.get("/api/progress", params={"tz": -180}).json()
    assert moscow["calendar"] == ["2026-08-03", "2026-10-21"]
    utc = weekly.get("/api/progress", params={"tz": 0}).json()
    assert utc["calendar"] == ["2026-10-20", "2026-10-21"]


def test_weeks_start_mondays_and_rating_change(weekly, db_path):
    attempts(
        db_path,
        [
            ("2026-10-13T10:00:00Z", 1, 600.0, 620.0),
            ("2026-10-14T10:00:00Z", 0, 620.0, 605.0),
            ("2026-10-15T10:00:00Z", 1, 605.0, 640.4),
            ("2026-10-06T10:00:00Z", 0, 590.0, 580.0),
        ],
    )
    weeks = weekly.get("/api/progress", params={"tz": 0}).json()["weeks"]
    assert [w["start"] for w in weeks] == [
        "2026-08-31",
        "2026-09-07",
        "2026-09-14",
        "2026-09-21",
        "2026-09-28",
        "2026-10-05",
        "2026-10-12",
        "2026-10-19",
    ]
    assert weeks[6] == {
        "start": "2026-10-12",
        "active_days": 3,
        "puzzles_solved": 2,
        "rating_change": 40,
        "player_moves": 0,
        "blunders_per_10_moves": None,
    }
    assert weeks[5]["rating_change"] == -10 and weeks[5]["puzzles_solved"] == 0
    assert weeks[7]["rating_change"] == 0 and weeks[7]["active_days"] == 0


def test_blunders_per_10_moves_by_week(weekly, db_path):
    run(
        db_path,
        "INSERT INTO games (user_id, created_at, player_color, result, moves_count, pgn)"
        " VALUES ((SELECT MIN(id) FROM users), ?, ?, '1-0', ?, 'x')",
        [
            ("2026-10-13T10:00:00Z", "white", 41),
            ("2026-10-14T10:00:00Z", "black", 40),
            ("2026-10-20T10:00:00Z", "white", 10),
        ],
    )
    run(
        db_path,
        "INSERT INTO mistakes (user_id, source, ref, fen, best_uci, best_san, classification,"
        " created_at, due_at, reviews, lapses)"
        " VALUES ((SELECT MIN(id) FROM users), ?, ?, 'f', 'e2e4', 'e4', ?, ?, 'n', 0, 0)",
        [
            ("game", "1", "blunder", "2026-10-13T11:00:00Z"),
            ("play", "2", "blunder", "2026-10-15T11:00:00Z"),
            ("game", "3", "mistake", "2026-10-15T11:00:00Z"),
            ("puzzle", "4", "blunder", "2026-10-15T11:00:00Z"),
            ("play", "5", "blunder", "2026-10-06T11:00:00Z"),
        ],
    )
    weeks = weekly.get("/api/progress", params={"tz": 0}).json()["weeks"]
    # 21 + 20 own moves and 2 blunders from games and play.
    assert weeks[6]["player_moves"] == 41 and weeks[6]["blunders_per_10_moves"] == 0.49
    assert weeks[7]["player_moves"] == 5 and weeks[7]["blunders_per_10_moves"] == 0.0
    assert weeks[5]["player_moves"] == 0 and weeks[5]["blunders_per_10_moves"] is None


@pytest.mark.parametrize(("tz", "week"), [(-180, 7), (0, 6)])
def test_sunday_evening_events_fall_into_local_week(weekly, db_path, tz, week):
    # 22:00Z on Sunday 10-18 is Monday 10-19 in Moscow (this week) and Sunday in UTC (last week).
    stamp = "2026-10-18T22:00:00Z"
    attempts(db_path, [(stamp, 1, 600.0, 625.0)])
    run(
        db_path,
        "INSERT INTO games (user_id, created_at, player_color, result, moves_count, pgn)"
        " VALUES ((SELECT MIN(id) FROM users), ?, 'white', '1-0', 20, 'x')",
        [(stamp,)],
    )
    run(
        db_path,
        "INSERT INTO mistakes (user_id, source, ref, fen, best_uci, best_san, classification,"
        " created_at, due_at, reviews, lapses)"
        " VALUES ((SELECT MIN(id) FROM users), 'game', '1', 'f', 'e2e4', 'e4', 'blunder', ?,"
        " 'n', 0, 0)",
        [(stamp,)],
    )
    weeks = weekly.get("/api/progress", params={"tz": tz}).json()["weeks"]
    other = 13 - week  # the other one of weeks 6 and 7
    # 10 own moves of white in 20 half-moves and 1 blunder.
    assert weeks[week]["rating_change"] == 25 and weeks[week]["player_moves"] == 10
    assert weeks[week]["blunders_per_10_moves"] == 1.0
    assert weeks[other]["rating_change"] == 0 and weeks[other]["player_moves"] == 0
    assert weeks[other]["blunders_per_10_moves"] is None


def test_weeks_count_only_this_user(weekly, db_path):
    conn = connect(db_path)
    with conn:
        other = conn.execute(
            "INSERT INTO users (login, token_hash, created_at) VALUES ('other', 'x', ?)", (NOW,)
        ).lastrowid
        conn.execute(
            "INSERT INTO puzzle_attempts (user_id, puzzle_id, created_at, solved, used_hint,"
            " puzzle_rating, rating_before, rating_after)"
            " VALUES (?, 'p', '2026-10-20T10:00:00Z', 1, 0, 700, 600, 650)",
            (other,),
        )
    conn.close()
    data = weekly.get("/api/progress", params={"tz": 0}).json()
    assert data["calendar"] == [] and data["weeks"][7]["rating_change"] == 0


@pytest.mark.parametrize("tz", [-841, 841, "x"])
def test_progress_tz_validation(client, tz):
    assert client.get("/api/progress", params={"tz": tz}).status_code == 422
