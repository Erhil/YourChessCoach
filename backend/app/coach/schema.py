from typing import Literal

from pydantic import BaseModel

from app.coach.motifs import Motif
from app.coach.why import Reason


class MoveRef(BaseModel):
    san: str
    uci: str


class Eval(BaseModel):
    cp: int | None
    mate: int | None


class Material(BaseModel):
    change: int
    lost: list[str]
    gained: list[str]


class Threat(BaseModel):
    move_san: str
    mate_in: int | None
    material: int | None
    wins: list[str] = []  # pieces the threat wins (net), e.g. ["N"]


class Lesson(BaseModel):
    slug: str
    title: str


class CoachFacts(BaseModel):
    fen_before: str
    side: Literal["white", "black"]
    player_move: MoveRef
    classification: Literal["best", "good", "inaccuracy", "mistake", "blunder"]
    win_chance_drop: float
    eval_before: Eval
    eval_after: Eval
    best_move: MoveRef | None
    best_line: list[str]
    refutation: list[str]
    material: Material
    missed_material: Material
    motifs_against: list[Motif]
    motifs_missed: list[Motif]
    reasons_against: list[Reason] = []
    reasons_missed: list[Reason] = []
    allowed_mate_in: int | None
    missed_mate_in: int | None
    threat: Threat | None
    lesson: Lesson | None
    game_over: Literal["checkmate", "stalemate", "draw"] | None = None
