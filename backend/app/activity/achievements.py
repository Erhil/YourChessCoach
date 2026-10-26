"""Achievements: the catalogue and the award on request. An earned achievement stays earned."""

import math
import sqlite3
from pathlib import Path

from app.activity.days import Activity, activity_state, comeback
from app.db import TRAINING_GAME
from app.mistakes.srs import now_utc
from app.progress.routes import build_progress
from app.puzzles.rating import START_RATING
from app.puzzles.themes import OFFERED

NEXT_COUNT = 3

# (key, title, text, goal, metric, target, unit); a hidden achievement is not shown before it is
# earned. `goal` is the text of a not-earned achievement in `next`: it states the goal, not the
# result. `unit` is the word after "из N" in `next` (genitive plural).
# An achievement without a goal (None) is never in `next`: a hidden one, and week_goal, because
# the week block on the today page already shows the days of the week.
CATALOGUE = [
    (
        "first_puzzle",
        "Первая задача",
        "Вы решили первую задачу.",
        "Решите первую задачу.",
        "solved",
        1,
        "задач",
    ),
    (
        "first_lesson",
        "Первый урок",
        "Вы прошли первый урок до конца.",
        "Пройдите первый урок до конца.",
        "lessons",
        1,
        "уроков",
    ),
    (
        "first_game",
        "Первая партия",
        "Вы доиграли первую партию до конца.",
        "Доиграйте партию до конца.",
        "finished",
        1,
        "партий",
    ),
    (
        "first_card",
        "Ошибка исправлена",
        "Вы три раза подряд нашли ход, который раньше пропустили.",
        "Ответьте верно три раза подряд на одну карточку колоды.",
        "learned",
        1,
        "карточек",
    ),
    (
        "puzzles_25",
        "25 задач",
        "Вы решили 25 задач.",
        "Решите 25 задач.",
        "solved",
        25,
        "задач",
    ),
    (
        "theme_10",
        "10 задач на одну тему",
        "Вы сделали 10 задач на одну тему. Так тема закрепляется.",
        "Сделайте 10 задач на одну тему.",
        "theme_attempts",
        10,
        "задач",
    ),
    (
        "lessons_5",
        "Пять уроков",
        "Вы прошли пять уроков.",
        "Пройдите пять уроков.",
        "lessons",
        5,
        "уроков",
    ),
    (
        "win_1100",
        "Победа над уровнем 1100",
        "Вы обыграли соперника уровня 1100.",
        "Обыграйте соперника уровня 1100.",
        "wins_1100",
        1,
        "партий",
    ),
    (
        "mate",
        "Мат!",
        "Вы поставили мат сопернику.",
        "Поставьте мат сопернику.",
        "mates",
        1,
        "партий",
    ),
    (
        "clean_game",
        "Партия без зевков",
        "Вы сыграли партию от 20 ходов без единого зевка.",
        "Сыграйте партию от 20 ходов без зевков.",
        "clean_games",
        1,
        "партий",
    ),
    (
        "theme_plus_100",
        "Рост в теме",
        "Ваш рейтинг в одной из тем вырос на 100.",
        "Поднимите рейтинг в одной теме на 100.",
        "theme_gain",
        100,
        "очков рейтинга",
    ),
    (
        "week_goal",
        "Цель недели",
        "Вы выполнили цель недели.",
        None,
        "streak_weeks",
        1,
        None,
    ),
    (
        "weeks_4",
        "Четыре недели подряд",
        "Четыре недели подряд вы занимаетесь столько, сколько наметили.",
        "Выполняйте цель недели четыре недели подряд.",
        "streak_weeks",
        4,
        "недель",
    ),
    (
        "puzzles_100",
        "100 задач",
        "Вы решили 100 задач.",
        "Решите 100 задач.",
        "solved",
        100,
        "задач",
    ),
    (
        "cards_10",
        "10 исправленных ошибок",
        "Вы исправили 10 своих ошибок из колоды.",
        "Исправьте 10 своих ошибок из колоды.",
        "learned",
        10,
        "карточек",
    ),
    (
        "comeback",
        "С возвращением",
        "Вы вернулись после перерыва. Это важнее любой серии.",
        None,
        "comeback",
        1,
        None,
    ),
]

# Any finished game gives first_game; the other game metrics skip training games.
GAMES_SQL = f"""
SELECT TOTAL(result != '*') AS finished,
       TOTAL(won AND level >= 1100) AS wins_1100,
       TOTAL(won AND termination = 'checkmate') AS mates,
       TOTAL(result != '*' AND own_moves >= 20 AND blunders = 0 AND NOT training) AS clean_games
FROM (
    SELECT *, ((result = '1-0' AND player_color = 'white') OR (result = '0-1' AND player_color = 'black'))
        AND NOT {TRAINING_GAME} AS won, (moves_count + (player_color = 'white')) / 2 AS own_moves,
        {TRAINING_GAME} AS training
    FROM games WHERE user_id = ?
)
"""


def metrics(
    db: sqlite3.Connection, lessons_dir: Path, user_id: int, state: Activity
) -> dict[str, int]:
    """The current value of every metric of the catalogue for the user."""
    p = build_progress(db, lessons_dir, user_id)
    themes = p["themes"]
    # Raw ratings: build_progress rounds them, and 699.5 must not count as +100.
    ratings = [
        r[1]
        for r in db.execute(
            "SELECT scope, rating FROM user_ratings"
            " WHERE user_id = ? AND scope != 'overall' AND attempts >= 1",
            (user_id,),
        )
        if r[0] in OFFERED
    ]
    games = db.execute(GAMES_SQL, (user_id,)).fetchone()
    today = state.today
    return {
        "solved": p["puzzles"]["solved"],
        "lessons": p["lessons"]["completed"],
        "learned": p["mistakes"]["learned"],
        "theme_attempts": max((t["attempts"] for t in themes), default=0),
        "theme_gain": max((math.floor(r - START_RATING) for r in ratings), default=0),
        "streak_weeks": state.week["streak_weeks"],
        "comeback": int(comeback(state.active, today) and today in state.counts),
        **{k: int(games[k]) for k in ("finished", "wins_1100", "mates", "clean_games")},
    }


def _met(values: dict[str, int]) -> list[str]:
    return [key for key, _, _, _, metric, target, _ in CATALOGUE if values[metric] >= target]


def earned_titles(db: sqlite3.Connection, user_id: int) -> list[str]:
    """Titles of the stored achievements (the ones the app awarded), without a write."""
    stored = {
        r[0] for r in db.execute("SELECT key FROM achievements WHERE user_id = ?", (user_id,))
    }
    return [title for key, title, *_ in CATALOGUE if key in stored]


def _stored(db: sqlite3.Connection, user_id: int) -> dict:
    return {
        r["key"]: r
        for r in db.execute(
            "SELECT key, earned_at, seen FROM achievements WHERE user_id = ?", (user_id,)
        )
    }


def award(
    db: sqlite3.Connection,
    lessons_dir: Path,
    user_id: int,
    tz: int,
    state: Activity | None = None,
) -> dict:
    """Store the newly met achievements; return {earned, new, next}.

    `state` is the activity that the caller already read; without it, award reads it.
    """
    state = state or activity_state(db, user_id, tz, now_utc())
    values = metrics(db, lessons_dir, user_id, state)
    stored = _stored(db, user_id)
    missing = [key for key in _met(values) if key not in stored]
    if missing:  # a write transaction only when there is something to store
        with db:
            # OR IGNORE: a parallel request can store the same key first.
            db.executemany(
                "INSERT OR IGNORE INTO achievements (user_id, key, earned_at) VALUES (?, ?, ?)",
                [(user_id, key, now_utc()) for key in missing],
            )
        stored = _stored(db, user_id)
    earned, new, todo = [], [], []
    for i, (key, title, text, goal_text, metric, target, unit) in enumerate(CATALOGUE):
        item = {"key": key, "title": title, "text": text}
        if key in stored:
            earned.append(item | {"earned_at": stored[key]["earned_at"]})
            if not stored[key]["seen"]:
                new.append(earned[-1])
        elif goal_text is not None:
            progress = min(max(values[metric], 0), target)
            goal = {"key": key, "title": title, "text": goal_text, "unit": unit}
            todo.append((-progress / target, i, goal | {"progress": progress, "target": target}))
    return {"earned": earned, "new": new, "next": [x[2] for x in sorted(todo)[:NEXT_COUNT]]}


def mark_seen(db: sqlite3.Connection, user_id: int, keys: list[str]) -> None:
    with db:
        db.executemany(
            "UPDATE achievements SET seen = 1 WHERE user_id = ? AND key = ?",
            [(user_id, k) for k in keys],
        )
