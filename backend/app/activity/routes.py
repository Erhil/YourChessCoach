from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from app.activity.achievements import CATALOGUE, award, mark_seen
from app.activity.days import KINDS, Tz, activity_state, comeback, server_tz
from app.auth.deps import UserId
from app.db import Db
from app.mistakes.srs import now_utc

router = APIRouter(prefix="/api/activity")
achievements_router = APIRouter(prefix="/api/achievements")


class Goal(BaseModel):
    goal: Literal[3, 4, 5]


class Seen(BaseModel):
    keys: list[str] = Field(max_length=50)


@router.get("")
def activity(request: Request, db: Db, user_id: UserId, tz: int | None = Tz) -> dict:
    tz = server_tz() if tz is None else tz
    state = activity_state(db, user_id, tz, now_utc())
    today_counts = state.counts.get(state.today, {})
    data = award(db, request.app.state.settings.lessons_dir, user_id, tz, state)
    return {
        "date": state.today.isoformat(),
        "today": {kind: today_counts.get(kind, 0) for kind in KINDS},
        "week": state.week,
        "comeback": comeback(state.active, state.today),
        "achievements": {"new": data["new"], "next": data["next"]},
    }


@router.post("/goal", status_code=204)
def set_goal(body: Goal, db: Db, user_id: UserId) -> Response:
    with db:
        db.execute("UPDATE users SET week_goal = ? WHERE id = ?", (body.goal, user_id))
    return Response(status_code=204)


@achievements_router.get("")
def achievements(request: Request, db: Db, user_id: UserId, tz: int | None = Tz) -> dict:
    tz = server_tz() if tz is None else tz
    data = award(db, request.app.state.settings.lessons_dir, user_id, tz)
    return {"earned": data["earned"], "next": data["next"], "total": len(CATALOGUE)}


@achievements_router.post("/seen", status_code=204)
def seen(body: Seen, db: Db, user_id: UserId) -> Response:
    mark_seen(db, user_id, body.keys)
    return Response(status_code=204)
