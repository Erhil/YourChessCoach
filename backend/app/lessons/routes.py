import sqlite3

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth.deps import UserId
from app.coach.explain import TEMPLATE_MODEL, current_model
from app.db import Db
from app.lessons import ask
from app.lessons.loader import is_completed, list_lessons, position_count
from app.llm.client import LLMError
from app.security import ENGINE_HEAVY

router = APIRouter(prefix="/api/lessons")


class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=300)
    position: int | None = None


def _all(request: Request) -> list[dict]:
    return list_lessons(request.app.state.settings.lessons_dir)


def _solved(db: sqlite3.Connection, user_id: int, slug: str) -> list[int]:
    rows = db.execute(
        "SELECT position FROM lesson_progress WHERE user_id = ? AND slug = ? ORDER BY position",
        (user_id, slug),
    )
    return [r[0] for r in rows]


def _find(request: Request, slug: str) -> dict:
    for x in _all(request):
        if x["slug"] == slug:
            return x
    raise HTTPException(status_code=404, detail="Lesson not found")


@router.get("")
def lessons(request: Request, db: Db, user_id: UserId) -> list[dict]:
    out = []
    for x in _all(request):
        n = position_count(x)
        solved = len(_solved(db, user_id, x["slug"]))
        out.append(
            {
                **{k: v for k, v in x.items() if k != "segments"},
                "positions": n,
                "solved": solved,
                "completed": is_completed(x, solved),
            }
        )
    return out


@router.get("/{slug}")
def lesson(slug: str, request: Request, db: Db, user_id: UserId) -> dict:
    return {**_find(request, slug), "solved": _solved(db, user_id, slug)}


@router.post("/{slug}/positions/{index}")
def solve_position(slug: str, index: int, request: Request, db: Db, user_id: UserId) -> dict:
    lesson = _find(request, slug)
    n = position_count(lesson)
    if not 0 <= index < n:
        raise HTTPException(status_code=404, detail="Position not found")
    db.execute(
        "INSERT OR IGNORE INTO lesson_progress (user_id, slug, position) VALUES (?, ?, ?)",
        (user_id, slug, index),
    )
    db.commit()
    solved = _solved(db, user_id, slug)
    return {"solved": solved, "positions": n, "completed": is_completed(lesson, len(solved))}


@router.post("/{slug}/ask", dependencies=ENGINE_HEAVY)
def ask_coach(slug: str, body: AskBody, request: Request, db: Db) -> dict:
    lesson = _find(request, slug)
    blocks = [s for s in lesson["segments"] if s["type"] == "chess"]
    if body.position is not None and not 0 <= body.position < len(blocks):
        raise HTTPException(status_code=404, detail="Position not found")
    settings, llm = request.app.state.settings, request.app.state.llm
    if not settings.llm_enabled:
        return {"answer": None, "source": None, "reason": ask.UNAVAILABLE}
    model = current_model(db, settings)
    if model == TEMPLATE_MODEL:
        return {"answer": None, "source": None, "reason": ask.UNAVAILABLE}
    context = ask.lesson_context(lesson)
    facts = None
    if body.position is not None:
        b = blocks[body.position]
        facts = ask.position_facts(
            b["fen"], b["solution"], ask.best_line(b["fen"], request.app.state.pool)
        )
    try:
        text = llm.chat(ask.SYSTEM, ask.build_user(body.question, context, facts), model)
    except LLMError as exc:
        ask.log.warning("lesson question skipped: %s", exc)
        return {"answer": None, "source": None, "reason": ask.UNAVAILABLE}
    try:
        text = ask.render_response(text, context)
    except ValueError as exc:
        ask.log.warning("lesson answer rejected: %s", exc)
        return {"answer": None, "source": None, "reason": ask.INEXACT}
    return {"answer": text, "source": "llm", "reason": None}
