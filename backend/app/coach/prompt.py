"""Prompt for the LLM coach: compact facts and trusted prose for study-advice selection."""

import json
import re

from app.coach.motifs import Motif
from app.coach.schema import CoachFacts
from app.coach.templates import _net, explain
from app.coach.why import Reason

GLYPHS = {"♔": "K", "♕": "Q", "♖": "R", "♗": "B", "♘": "N"}
GLYPHS |= {"♚": "K", "♛": "Q", "♜": "R", "♝": "B", "♞": "N"}

# The model selects study advice. It never writes user-visible chess claims.
CONTRACT_VERSION = "trusted-coach-v1"
TIPS = {
    "none": "",
    "repeat": "После партии вернитесь к этой позиции и повторите проверку.",
    "explain": "Закрепите этот разбор: попробуйте объяснить причину хода своими словами.",
}
SYSTEM = (
    "Выбери дополнительный учебный совет для новичка по фактам и готовому разбору. "
    'Ответь только JSON вида {"tip":"repeat"}. '
    "Допустимые значения tip перечислены в запросе. Не добавляй других полей или текста. "
    "Не переписывай разбор и ходы в SAN. Если дополнительный совет не нужен, выбери none."
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
    return SYSTEM, f"Факты: {data}\nРазбор: {draft}\nСоветы: {json.dumps(TIPS, ensure_ascii=False)}"
