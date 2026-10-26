"""Prompt for the LLM coach: compact facts as JSON plus the template text as a draft."""

import json
import re

from app.coach.motifs import Motif
from app.coach.schema import CoachFacts
from app.coach.templates import _net, explain
from app.coach.why import Reason

GLYPHS = {"♔": "K", "♕": "Q", "♖": "R", "♗": "B", "♘": "N"}
GLYPHS |= {"♚": "K", "♛": "Q", "♜": "R", "♝": "B", "♞": "N"}

# Rules of the answer text, shared with the question prompt in ask.py.
RULES = (
    "Используй ТОЛЬКО ходы и поля, которые есть в фактах. "
    "Ходы пиши в SAN латинскими буквами точно так, как в фактах (например Nf3, Qxh4, O-O). "
    "Не выдумывай ходы и поля. Не называй числа оценки позиции. "
    "Фигуры на доске называй словами с полем: «конь на f3», «ферзь на h4». "
    "Обращайся к ученику на «вы». Без списков и без разметки."
)
SYSTEM = (
    "Ты — дружелюбный шахматный тренер для новичка. Тебе дают факты о ходе игрока в JSON "
    "и черновик объяснения. Перепиши черновик по-русски в 2–4 коротких предложениях: "
    "что случилось, почему, как заметить это в следующий раз. "
    + RULES
    + " Ход в SAN пиши, только если он есть среди ходов в фактах. Упоминай не больше двух ходов. "
    "Если в фактах есть reasons_against (что сломал ход ученика) или reasons_missed (что давал "
    "лучший ход), назови причину конкретно, с фигурой и полем, как учитель ученику: "
    "«конь ушёл с f3 и больше не защищает пешку e5». Не называй причину, которой нет в фактах. "
    "Ход игрока — это ход ученика, ответ — ход соперника; не путай их. "
    "Сильнейший ответ соперника из фактов (refutation, threat) называй как возможность: "
    "«соперник может ответить Qxg5», а не «соперник ответит Qxg5»: настоящий соперник "
    "может сыграть другой ход. Мат в фактах (allowed_mate_in) называй как факт. "
    "Пат — это ничья."
)


def figurine_to_san(text: str) -> str:
    """♘c7+ -> Nc7+, e8=♕ -> e8=Q."""
    return re.sub("[" + "".join(GLYPHS) + "]", lambda m: GLYPHS[m[0]], text)


def _piece(item: dict[str, str]) -> str:
    return f"{item['piece'].upper()} {item['square']}"


def _motifs(motifs: list[Motif]) -> list[dict]:
    return [
        {"kind": m.kind, "by": _piece(m.by), "targets": [_piece(t) for t in m.targets]}
        | ({"move": m.move_san} if m.move_san else {})
        for m in motifs
    ]


def _reasons(reasons: list[Reason]) -> list[dict]:
    return [
        {"kind": r.kind, "pieces": [_piece(p) for p in r.pieces], "squares": r.squares}
        | ({"detail": r.detail} if r.detail else {})
        for r in reasons
    ]


def compact_facts(f: CoachFacts) -> dict:
    lost, gained = _net(f.material)
    d = {
        "player_move": f.player_move.san,
        "classification": f.classification,
        "best_move": f.best_move.san if f.best_move else None,
        "best_line": f.best_line[:4],
        "refutation": f.refutation[:4],
        "material_lost": sorted(lost.elements()),
        "material_gained": sorted(gained.elements()),
        "motifs_against": _motifs(f.motifs_against),
        "motifs_missed": _motifs(f.motifs_missed),
        "reasons_against": _reasons(f.reasons_against),
        "reasons_missed": _reasons(f.reasons_missed),
        "allowed_mate_in": f.allowed_mate_in,
        "missed_mate_in": f.missed_mate_in,
        "threat": f.threat.move_san if f.threat else None,
        "game_over": f.game_over,
    }
    return {k: v for k, v in d.items() if v not in (None, [], "")}


def build_messages(facts: CoachFacts, draft: str | None = None) -> tuple[str, str]:
    draft = figurine_to_san(draft if draft is not None else explain(facts))
    data = json.dumps(compact_facts(facts), ensure_ascii=False, separators=(",", ":"))
    return SYSTEM, f"Факты: {data}\nЧерновик: {draft}"
