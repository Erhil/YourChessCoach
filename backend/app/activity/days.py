"""Local days and weeks of activity. `tz` is JavaScript getTimezoneOffset(): local = UTC - tz minutes.

An active day is a local date with a puzzle attempt, a deck answer, a solved lesson position or a
saved game of the user.
"""

import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from fastapi import Query

from app.mistakes.srs import FORMAT

# Every event of the user with its local date; `shift` is an SQLite modifier like '+180 minutes'.
EVENTS_SQL = """
SELECT day, kind, COUNT(*) AS n FROM (
    SELECT date(created_at, :shift) AS day, 'puzzles' AS kind FROM puzzle_attempts WHERE user_id = :u
    UNION ALL SELECT date(created_at, :shift), 'cards' FROM card_reviews WHERE user_id = :u
    UNION ALL SELECT date(solved_at, :shift), 'lesson_positions' FROM lesson_progress
        WHERE user_id = :u
    UNION ALL SELECT date(created_at, :shift), 'games' FROM games WHERE user_id = :u
) GROUP BY day, kind
"""
KINDS = ("puzzles", "cards", "lesson_positions", "games")
# The `tz` query parameter of the routes that count local days; None means the server offset.
Tz = Query(None, ge=-840, le=840)


def server_tz() -> int:
    """The server's current UTC offset in the getTimezoneOffset() meaning (no tz database needed)."""
    return -int(datetime.now().astimezone().utcoffset().total_seconds() // 60)


def local_today(now_utc: str, tz: int) -> date:
    return (datetime.strptime(now_utc, FORMAT) - timedelta(minutes=tz)).date()


def local_day_utc(day: date, tz: int) -> tuple[str, str]:
    """The UTC range [start, end) of the local `day`, in the timestamp format of the tables."""
    start = datetime(day.year, day.month, day.day) + timedelta(minutes=tz)
    return start.strftime(FORMAT), (start + timedelta(days=1)).strftime(FORMAT)


def shift(tz: int) -> str:
    """The SQLite modifier that turns a UTC timestamp into local time."""
    return f"{-tz:+d} minutes"


def event_counts(db: sqlite3.Connection, user_id: int, tz: int) -> dict[date, Counter]:
    """Return {local date: Counter(kind -> events)} for all activity of the user."""
    days: dict[date, Counter] = {}
    for row in db.execute(EVENTS_SQL, {"shift": shift(tz), "u": user_id}):
        days.setdefault(date.fromisoformat(row["day"]), Counter())[row["kind"]] = row["n"]
    return days


@dataclass(frozen=True)
class Activity:
    """The activity of the user on the local `today`: one `event_counts` query and the week."""

    today: date
    counts: dict[date, Counter]
    week: dict

    @property
    def active(self) -> set[date]:
        return set(self.counts)


def activity_state(db: sqlite3.Connection, user_id: int, tz: int, now_utc: str) -> Activity:
    today = local_today(now_utc, tz)
    counts = event_counts(db, user_id, tz)
    goal = db.execute("SELECT week_goal FROM users WHERE id = ?", (user_id,)).fetchone()[0]
    return Activity(today, counts, week(set(counts), today, goal))


def week(active: set[date], today: date, goal: int) -> dict:
    start = today - timedelta(days=today.weekday())
    days = [start + timedelta(days=i) in active for i in range(7)]
    met = sum(days) >= goal
    # Past weeks are measured against the current goal: the goal history is not stored.
    streak, past = 0, start - timedelta(days=7)
    while sum(past + timedelta(days=i) in active for i in range(7)) >= goal:
        streak, past = streak + 1, past - timedelta(days=7)
    return {
        "start": start.isoformat(),
        "goal": goal,
        "days": days,
        "active_days": sum(days),
        "met": met,
        # A current week that is not met yet does not break the streak.
        "streak_weeks": streak + int(met),
    }


def comeback(active: set[date], today: date) -> bool:
    """True after 3 or more whole days without activity between the last active day and today."""
    before = [d for d in active if d < today]
    return bool(before) and (today - max(before)).days - 1 >= 3
