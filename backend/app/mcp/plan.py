"""Plans saved by the senior coach (a big model over MCP). History is kept; the newest row counts."""

import json
import sqlite3
from datetime import UTC, datetime

from fastapi import APIRouter

from app.auth.deps import UserId
from app.db import Db

router = APIRouter(prefix="/api/plan")

KEEP_PLANS = 20


def latest_plan(db: sqlite3.Connection, user_id: int) -> dict | None:
    row = db.execute(
        "SELECT created_at, summary, focus_themes, lessons, openings FROM plans"
        " WHERE user_id = ? ORDER BY id DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "created_at": row["created_at"],
        "summary": row["summary"],
        "focus_themes": json.loads(row["focus_themes"]),
        "lessons": json.loads(row["lessons"]),
        "openings": json.loads(row["openings"]),
    }


def insert_plan(
    db: sqlite3.Connection,
    user_id: int,
    summary: str,
    focus_themes: list[str],
    lessons: list[str],
    openings: list[str],
) -> dict:
    with db:
        db.execute(
            "INSERT INTO plans (user_id, created_at, summary, focus_themes, lessons, openings)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                user_id,
                datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                summary,
                json.dumps(focus_themes),
                json.dumps(lessons),
                json.dumps(openings),
            ),
        )
        db.execute(
            "DELETE FROM plans WHERE user_id = ? AND id NOT IN"
            " (SELECT id FROM plans WHERE user_id = ? ORDER BY id DESC LIMIT ?)",
            (user_id, user_id, KEEP_PLANS),
        )
    plan = latest_plan(db, user_id)
    assert plan is not None
    return plan


@router.get("")
def get_plan(db: Db, user_id: UserId) -> dict:
    return {"plan": latest_plan(db, user_id)}
