import sqlite3
from dataclasses import replace

import pytest
from conftest import TEST_LOGIN
from fastapi.testclient import TestClient

from app.auth import service
from app.config import settings as default_settings
from app.db import connect
from app.main import create_app

# Wednesday; its week starts on Monday 2026-10-19.
NOW = "2026-10-21T12:00:00Z"
INSERT = {
    "puzzles": "INSERT INTO puzzle_attempts (user_id, puzzle_id, created_at, solved, used_hint,"
    " puzzle_rating, rating_before, rating_after) VALUES (?, 'p', ?, 1, 0, 800, 800, 810)",
    "cards": "INSERT INTO card_reviews (user_id, mistake_id, created_at, correct) VALUES (?, 1, ?, 1)",
    "lesson_positions": "INSERT INTO lesson_progress (user_id, slug, position, solved_at)"
    " VALUES (?, 'l', abs(random() % 1000000), ?)",
    "games": "INSERT INTO games (user_id, created_at, player_color, result, pgn, moves_count)"
    " VALUES (?, ?, 'white', '*', '1. e4 *', 1)",
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    for module in ("routes", "achievements"):
        monkeypatch.setattr(f"app.activity.{module}.now_utc", lambda: NOW)
    settings = replace(
        default_settings, app_db_path=tmp_path / "app.db", frontend_dist=tmp_path / "dist"
    )
    with TestClient(create_app(settings)) as c:
        c.db = connect(settings.app_db_path)
        c.user = c.db.execute("SELECT id FROM users WHERE login = ?", (TEST_LOGIN,)).fetchone()[0]
        yield c
        c.db.close()


def add(client, *stamps, kind="puzzles", user=None):
    with client.db:
        for ts in stamps:
            client.db.execute(INSERT[kind], (user or client.user, ts))


def get(client, tz=-180):
    r = client.get("/api/activity", params={"tz": tz})
    assert r.status_code == 200, r.text
    return r.json()


def test_empty_user(client):
    data = get(client)
    assert data == {
        "date": "2026-10-21",
        "today": {"puzzles": 0, "cards": 0, "lesson_positions": 0, "games": 0},
        "week": {
            "start": "2026-10-19",
            "goal": 3,
            "days": [False] * 7,
            "active_days": 0,
            "met": False,
            "streak_weeks": 0,
        },
        "comeback": False,
        "achievements": data["achievements"],  # covered by test_achievements.py
    }
    assert data["achievements"]["new"] == [] and len(data["achievements"]["next"]) == 3


def test_today_counts_every_kind(client):
    add(client, "2026-10-21T08:00:00Z", "2026-10-21T09:00:00Z")
    for kind in ("cards", "lesson_positions", "games"):
        add(client, "2026-10-21T10:00:00Z", kind=kind)
    assert get(client)["today"] == {"puzzles": 2, "cards": 1, "lesson_positions": 1, "games": 1}


def test_local_day_boundary(client, monkeypatch):
    # 22:30Z is 01:30 of the next day in Moscow (tz=-180), but the same day in UTC.
    monkeypatch.setattr("app.activity.routes.now_utc", lambda: "2026-10-20T22:30:00Z")
    add(client, "2026-10-20T22:30:00Z")
    moscow = get(client, tz=-180)
    assert moscow["date"] == "2026-10-21" and moscow["today"]["puzzles"] == 1
    assert moscow["week"]["days"] == [False, False, True, False, False, False, False]
    utc = get(client, tz=0)
    assert utc["date"] == "2026-10-20" and utc["week"]["days"][1]
    # New York (tz=240): an event at 02:00Z on Monday is still Sunday of the week before.
    add(client, "2026-10-19T02:00:00Z")
    assert get(client, tz=240)["week"]["days"][0] is False


def test_week_days_and_met(client):
    add(client, "2026-10-19T10:00:00Z", "2026-10-19T11:00:00Z")  # Monday, two events
    add(client, "2026-10-18T10:00:00Z")  # Sunday of the week before
    add(client, "2026-10-21T10:00:00Z", kind="games")
    week = get(client)["week"]
    assert week["days"] == [True, False, True, False, False, False, False]
    assert week["active_days"] == 2 and not week["met"]
    add(client, "2026-10-20T10:00:00Z", kind="lesson_positions")
    week = get(client)["week"]
    assert week["active_days"] == 3 and week["met"] and week["streak_weeks"] == 1


def days_of_week(monday: str, count: int) -> list[str]:
    """`count` days from the Monday `monday` (MM-DD) of 2026, all inside one week."""
    month, day = monday.split("-")
    return [f"2026-{month}-{int(day) + i:02d}T10:00:00Z" for i in range(count)]


def test_streak_weeks(client):
    # Weeks starting 28.09, 05.10 and 12.10 are met; the week of 21.09 has 2 days only.
    add(client, *days_of_week("09-21", 2), *days_of_week("09-28", 3))
    add(client, *days_of_week("10-05", 4), *days_of_week("10-12", 3))
    week = get(client)["week"]
    assert not week["met"] and week["streak_weeks"] == 3  # the current week does not break it
    add(client, *days_of_week("10-19", 3))
    assert get(client)["week"]["streak_weeks"] == 4
    # A higher goal applies to past weeks too: only the week of 05.10 has 4 days, and 12.10 breaks.
    assert client.post("/api/activity/goal", json={"goal": 4}).status_code == 204
    week = get(client)["week"]
    assert week["goal"] == 4 and not week["met"] and week["streak_weeks"] == 0


def test_streak_stops_at_week_not_met(client):
    # 21.09 and 05.10 weeks are met, the week of 28.09 has 2 days, 12.10 is met.
    add(client, *days_of_week("09-21", 3), *days_of_week("09-28", 2))
    add(client, *days_of_week("10-05", 3), *days_of_week("10-12", 3))
    assert get(client)["week"]["streak_weeks"] == 2


def test_today_is_sunday(client, monkeypatch):
    monkeypatch.setattr("app.activity.routes.now_utc", lambda: "2026-10-25T12:00:00Z")
    add(client, "2026-10-25T10:00:00Z")
    week = get(client)["week"]
    assert week["start"] == "2026-10-19"
    assert week["days"] == [False] * 6 + [True]


def test_week_crosses_year(client, monkeypatch):
    # Sunday 2027-01-03; the week starts on Monday 2026-12-28.
    monkeypatch.setattr("app.activity.routes.now_utc", lambda: "2027-01-03T12:00:00Z")
    add(client, *days_of_week("12-21", 3))
    add(client, "2026-12-28T10:00:00Z", "2026-12-31T10:00:00Z", "2027-01-02T10:00:00Z")
    week = get(client)["week"]
    assert week["start"] == "2026-12-28"
    assert week["days"] == [True, False, False, True, False, True, False]
    assert week["met"] and week["streak_weeks"] == 2
    # Next Wednesday: the past week 28.12–03.01 crosses the year and still counts.
    monkeypatch.setattr("app.activity.routes.now_utc", lambda: "2027-01-06T12:00:00Z")
    week = get(client)["week"]
    assert week["start"] == "2027-01-04" and not week["met"] and week["streak_weeks"] == 2


def test_comeback_boundary(client, monkeypatch):
    add(client, "2026-10-01T10:00:00Z")
    monkeypatch.setattr("app.activity.routes.now_utc", lambda: "2026-10-04T10:00:00Z")
    assert get(client)["comeback"] is False  # 2 whole days without activity
    monkeypatch.setattr("app.activity.routes.now_utc", lambda: "2026-10-05T10:00:00Z")
    assert get(client)["comeback"] is True  # 3 whole days
    add(client, "2026-10-05T08:00:00Z")
    assert get(client)["comeback"] is True  # activity today does not cancel the comeback


def test_no_comeback_without_earlier_activity(client):
    add(client, "2026-10-21T10:00:00Z")
    assert get(client)["comeback"] is False


def test_goal_validation(client):
    for goal in (3, 4, 5):
        assert client.post("/api/activity/goal", json={"goal": goal}).status_code == 204
    assert get(client)["week"]["goal"] == 5
    for bad in (2, 6, 0, "x", None):
        assert client.post("/api/activity/goal", json={"goal": bad}).status_code == 422
    assert client.post("/api/activity/goal", json={}).status_code == 422


def test_tz_validation(client):
    for tz in (-840, 840):
        assert client.get("/api/activity", params={"tz": tz}).status_code == 200
    for tz in (-841, 841, "x", "1.5"):
        assert client.get("/api/activity", params={"tz": tz}).status_code == 422
    assert client.get("/api/activity").status_code == 200  # the server's own offset


def test_other_user_is_not_counted(client):
    other = service.create_user(client.db, "other", "zzzz-zzzz-zzzz-zzzz")
    for kind in INSERT:
        add(client, "2026-10-21T10:00:00Z", "2026-10-20T10:00:00Z", kind=kind, user=other)
    data = get(client)
    assert data["today"] == {"puzzles": 0, "cards": 0, "lesson_positions": 0, "games": 0}
    assert data["week"]["active_days"] == 0


def test_activity_needs_login(tmp_path):
    settings = replace(
        default_settings, app_db_path=tmp_path / "app.db", frontend_dist=tmp_path / "dist"
    )
    with TestClient(create_app(settings), auto_login=False) as c:
        assert c.get("/api/activity").status_code == 401
        assert c.post("/api/activity/goal", json={"goal": 3}).status_code == 401


def test_fresh_database_is_version_12(tmp_path):
    connect(tmp_path / "fresh.db").close()
    conn = sqlite3.connect(tmp_path / "fresh.db")
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 12
    conn.close()
