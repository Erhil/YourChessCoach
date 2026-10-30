import io
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import chess.pgn
from fastapi import APIRouter, Request

from app.activity.days import Tz, event_counts, local_today, server_tz, shift
from app.auth.deps import UserId
from app.db import TRAINING_GAME, Db
from app.games.routes import player_move_count
from app.lessons.loader import is_completed, list_lessons
from app.mistakes.srs import now_utc
from app.puzzles.rating import START_RATING
from app.puzzles.themes import OFFERED, theme_name

router = APIRouter(prefix="/api/progress")

HISTORY_LIMIT = 200
WEAK_MIN_ATTEMPTS = 3
CALENDAR_WEEKS = 12
SUMMARY_WEEKS = 8


@router.get("")
def progress(request: Request, db: Db, user_id: UserId, tz: int | None = Tz) -> dict:
    tz = server_tz() if tz is None else tz
    data = build_progress(db, request.app.state.settings.lessons_dir, user_id)
    return data | build_weeks(db, user_id, tz, local_today(now_utc(), tz))


def own_moves(game: sqlite3.Row) -> int:
    headers = chess.pgn.read_headers(io.StringIO(game["pgn"]))
    initial_turn = headers.board().turn if headers is not None else chess.WHITE
    return player_move_count(game["moves_count"], game["player_color"], initial_turn)


def per_10(blunders: int, moves: int) -> float | None:
    return round(10 * blunders / moves, 2) if moves else None


def blunder_stats(games) -> dict:
    """Use only saved games with a complete count for both sides of the rate."""
    analyzed = [g for g in games if g["blunders"] is not None]
    moves = sum(map(own_moves, analyzed))
    blunders = sum(g["blunders"] for g in analyzed)
    return {
        "analyzed_games": len(analyzed),
        "analyzed_player_moves": moves,
        "blunders": blunders,
        "blunders_per_10_moves": per_10(blunders, moves),
    }


def build_weeks(db: sqlite3.Connection, user_id: int, tz: int, today: date) -> dict:
    """The active days of the last 12 weeks and the totals of the last 8 weeks, by local dates."""
    monday = today - timedelta(days=today.weekday())
    first = monday - timedelta(weeks=CALENDAR_WEEKS - 1)
    active = sorted(d for d in event_counts(db, user_id, tz) if first <= d <= today)
    starts = [monday - timedelta(weeks=i) for i in range(SUMMARY_WEEKS - 1, -1, -1)]

    def by_week(table: str, where: str, columns: str) -> dict[date, list[sqlite3.Row]]:
        rows: dict[date, list[sqlite3.Row]] = {}
        for r in db.execute(
            f"SELECT date(created_at, ?) AS day, {columns} FROM {table}"
            f" WHERE {where} AND date(created_at, ?) >= ? ORDER BY id",
            (shift(tz), user_id, shift(tz), starts[0].isoformat()),
        ):
            day = date.fromisoformat(r["day"])
            rows.setdefault(day - timedelta(days=day.weekday()), []).append(r)
        return rows

    attempts = by_week("puzzle_attempts", "user_id = ?", "solved, rating_before, rating_after")
    games = by_week("games", "user_id = ?", "player_color, moves_count, blunders, pgn")
    weeks = []
    for start in starts:
        tries, moves = attempts.get(start, []), sum(map(own_moves, games.get(start, [])))
        weeks.append(
            {
                "start": start.isoformat(),
                "active_days": sum(start <= d < start + timedelta(days=7) for d in active),
                "puzzles_solved": sum(t["solved"] for t in tries),
                "rating_change": round(tries[-1]["rating_after"] - tries[0]["rating_before"])
                if tries
                else 0,
                "player_moves": moves,
                "games": len(games.get(start, [])),
                **blunder_stats(games.get(start, [])),
            }
        )
    return {"calendar": [d.isoformat() for d in active], "weeks": weeks}


def build_progress(db: sqlite3.Connection, lessons_dir: Path, user_id: int) -> dict:
    def scalar(sql: str, *args) -> int:
        return db.execute(sql, (user_id, *args)).fetchone()[0]

    row = db.execute(
        "SELECT rating, attempts FROM user_ratings WHERE user_id = ? AND scope = 'overall'",
        (user_id,),
    ).fetchone()
    history = db.execute(
        "SELECT created_at, rating_after FROM puzzle_attempts WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, HISTORY_LIMIT),
    ).fetchall()
    themes = sorted(
        (
            {"key": r["scope"], "name": theme_name(r["scope"]), "rating": round(r["rating"])}
            | {"attempts": r["attempts"]}
            for r in db.execute(
                "SELECT scope, rating, attempts FROM user_ratings WHERE user_id = ? AND scope != 'overall'",
                (user_id,),
            )
            if r["scope"] in OFFERED and r["attempts"] >= 1
        ),
        key=lambda t: (t["rating"], t["key"]),
    )
    weak = next((t for t in themes if t["attempts"] >= WEAK_MIN_ATTEMPTS), None)

    wins = losses = draws = player_moves = training = 0
    games = db.execute(
        f"SELECT player_color, result, moves_count, blunders, pgn, {TRAINING_GAME} AS training FROM games"
        " WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    for g in games:
        white = g["player_color"] == "white"
        player_moves += own_moves(g)
        # The blunder rate counts training games too; their result does not count.
        # An unfinished game is in no bucket, also when it is a training game.
        if g["result"] == "*":
            continue
        if g["training"]:
            training += 1
        elif g["result"] == "1/2-1/2":
            draws += 1
        else:
            wins += (g["result"] == "1-0") == white
            losses += (g["result"] == "1-0") != white

    solved = {
        r["slug"]: r["n"]
        for r in db.execute(
            "SELECT slug, COUNT(*) AS n FROM lesson_progress WHERE user_id = ? GROUP BY slug",
            (user_id,),
        )
    }
    lessons = list_lessons(lessons_dir)
    completed = sum(is_completed(x, solved.get(x["slug"], 0)) for x in lessons)

    return {
        "puzzles": {
            "rating": round(row["rating"]) if row else round(START_RATING),
            "attempts": row["attempts"] if row else 0,
            "solved": scalar(
                "SELECT COUNT(*) FROM puzzle_attempts WHERE user_id = ? AND solved = 1"
            ),
            "history": [
                {"at": h["created_at"], "rating": round(h["rating_after"])}
                for h in reversed(history)
            ],
        },
        "themes": themes,
        "weak_theme": {"key": weak["key"], "name": weak["name"]} if weak else None,
        "games": {
            "count": len(games),
            "wins": wins,
            "losses": losses,
            "draws": draws,
            "training": training,
            "player_moves": player_moves,
            **blunder_stats(games),
        },
        "lessons": {"completed": completed, "total": len(lessons)},
        "mistakes": {
            "total": scalar("SELECT COUNT(*) FROM mistakes WHERE user_id = ?"),
            "due": scalar(
                "SELECT COUNT(*) FROM mistakes WHERE user_id = ? AND due_at <= ? AND learned_at IS NULL",
                now_utc(),
            ),
            "learned": scalar(
                "SELECT COUNT(*) FROM mistakes WHERE user_id = ? AND learned_at IS NOT NULL"
            ),
        },
    }
