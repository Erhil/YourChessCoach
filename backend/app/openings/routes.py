from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.lessons.loader import list_lessons
from app.openings.lookup import family_of, find_opening, opening_card
from app.openings.names import ru_name
from app.puzzles.routes import _families

router = APIRouter(prefix="/api/openings")

MISSING = "Справочник дебютов не найден. Выполните: python scripts/download_openings.py"
BAD_MOVE = "Недопустимый ход в списке"


class MovesIn(BaseModel):
    moves: list[str] = Field(max_length=600)


def _book(request: Request):
    path = request.app.state.settings.app_data_dir / "openings.tsv"
    if not path.is_file():
        raise HTTPException(503, MISSING)
    return path


@router.post("/name")
def opening_name(body: MovesIn, request: Request) -> dict | None:
    path = _book(request)
    try:
        found = find_opening(path, body.moves)
    except ValueError as ex:  # illegal or malformed move
        raise HTTPException(422, BAD_MOVE) from ex
    return found and {**found, "name": ru_name(found["name"])}


@router.get("/card")
def opening_card_route(request: Request, moves: str = Query("", max_length=4000)) -> dict:
    path = _book(request)
    try:
        card = opening_card(path, moves.split())
    except ValueError as ex:
        raise HTTPException(422, BAD_MOVE) from ex
    if not card:
        raise HTTPException(404, "Дебют не найден")
    family = family_of(card["name"])
    settings = request.app.state.settings
    lesson = next(
        (
            {"slug": x["slug"], "title": x["title"]}
            for x in list_lessons(settings.lessons_dir)
            if family in x["openings"]
        ),
        None,
    )
    key = family.replace(" ", "_")
    has_db = settings.puzzles_db_path.is_file()
    return {
        "eco": card["eco"],
        "name": ru_name(card["name"]),
        "line_san": card["line_san"],
        "continuations": [{**c, "name": ru_name(c["name"])} for c in card["continuations"]],
        "lesson": lesson,
        "puzzles": key if has_db and key in _families(request) else None,
    }
