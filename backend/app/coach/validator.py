"""Render bounded model selections with trusted prose and display notation."""

import json
import re

from app.coach.prompt import TIPS, figurine_to_san
from app.coach.schema import CoachFacts
from app.coach.templates import explain, fig

PIECE_MOVE = r"[KQRBN][a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?[+#]?"
PAWN_MOVE = r"[a-h](?:x[a-h])?[1-8](?:=[QRBN])?[+#]?"
_SAN = rf"(?<![A-Za-z0-9])(O-O(?:-O)?[+#]?|{PIECE_MOVE}|{PAWN_MOVE})(?![A-Za-z0-9])"
SAN = re.compile(_SAN)


def to_display(text: str) -> str:
    """Figurine notation for the UI: Nf3 -> ♘f3. Use it on trusted text."""
    return SAN.sub(lambda m: fig(m[1]), figurine_to_san(text))


def render_response(payload: str, facts: CoachFacts) -> str:
    """Render trusted prose only from a bounded study-advice selection."""
    try:
        choice = json.loads(payload)
    except (ValueError, TypeError) as exc:
        raise ValueError("expected coach selection JSON") from exc
    if (
        not isinstance(choice, dict)
        or set(choice) != {"tip"}
        or not isinstance(choice["tip"], str)
        or choice["tip"] not in TIPS
    ):
        raise ValueError("unknown coach selection")
    core = explain(facts)
    tip = TIPS[choice["tip"]]
    sentences = [s for s in re.split(r"[.!?…]+(?:\s|$)", core) if s.strip()]
    if tip and len(sentences) < 4 and tip not in core:
        return f"{core} {tip}"
    return core
