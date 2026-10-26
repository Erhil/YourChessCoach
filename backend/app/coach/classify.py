"""Move classification by the drop of win chance (mover's point of view)."""

import math

import chess

from app.config import Settings

BEST_EPSILON = 0.04  # a drop this small is noise: the move is as good as the best
LOST = -0.9  # the mover is already lost: a faster mate is not a new blunder
ORDER = ["best", "good", "inaccuracy", "mistake", "blunder"]


def win_chance(cp: int) -> float:
    return 2 / (1 + math.exp(-0.00368208 * cp)) - 1


def score_win_chance(cp: int | None, mate: int | None) -> float:
    """Win chance of the side the score belongs to. A mate score counts as +-1."""
    if mate is not None:
        return 1.0 if mate > 0 else -1.0
    return win_chance(cp or 0)


def mover_view(score: dict, color: chess.Color) -> dict:
    """Score from White's view -> the view of `color`."""
    sign = 1 if color == chess.WHITE else -1
    return {k: None if v is None else sign * v for k, v in score.items()}


def thresholds(s: Settings) -> tuple[float, float, float]:
    return (s.coach_inaccuracy, s.coach_mistake, s.coach_blunder)


def missed_leads(loss_change: int, missed_change: int, missed_mate: int | None) -> bool:
    """True if the missed gain (or mate) matters more than the actual material loss."""
    return bool(missed_mate) or missed_change > abs(min(0, loss_change))


def _at_least(current: str, floor: str) -> str:
    return max(current, floor, key=ORDER.index)


def classify(
    wc_before: float,
    wc_after: float,
    is_best: bool,
    mate_before: int | None,
    mate_after: int | None,
    thresholds: tuple[float, float, float],
) -> str:
    """Mate numbers are from the mover's view: positive = the mover mates."""
    if is_best:
        return "best"
    if wc_before <= LOST:
        mate_after = None
    drop = wc_before - wc_after
    inaccuracy, mistake, blunder = thresholds
    if drop < BEST_EPSILON:
        result = "best"
    elif drop < inaccuracy:
        result = "good"
    elif drop < mistake:
        result = "inaccuracy"
    elif drop < blunder:
        result = "mistake"
    else:
        result = "blunder"
    if mate_after is not None and mate_after < 0 and not (mate_before and mate_before < 0):
        result = _at_least(result, "blunder")
    if mate_before and mate_before > 0 and not (mate_after and mate_after > 0):
        result = _at_least(result, "mistake")
    return result
