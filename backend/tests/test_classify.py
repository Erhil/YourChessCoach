import pytest

from app.coach.classify import classify, score_win_chance, win_chance

T = (0.10, 0.20, 0.30)


def test_win_chance_range_and_symmetry():
    assert win_chance(0) == 0
    assert win_chance(-300) == pytest.approx(-win_chance(300))
    assert -1 < win_chance(-2000) < win_chance(2000) < 1


def test_mate_counts_as_one():
    assert score_win_chance(None, 3) == 1.0
    assert score_win_chance(None, -2) == -1.0
    assert score_win_chance(0, None) == 0.0


@pytest.mark.parametrize(
    ("drop", "expected"),
    [
        (0.0, "best"),
        (-0.05, "best"),
        (0.007, "best"),
        (0.039, "best"),
        (0.041, "good"),
        (0.06, "good"),
        (0.15, "inaccuracy"),
    ]
    + [(0.25, "mistake"), (0.35, "blunder")],
)
def test_thresholds(drop, expected):
    assert classify(0.0, -drop, False, None, None, T) == expected


def test_played_best_move_is_best_even_with_noise():
    assert classify(0.5, 0.2, True, None, None, T) == "best"


def test_allowing_mate_is_at_least_blunder():
    assert classify(0.95, 0.94, False, None, -3, T) == "blunder"


def test_already_lost_mate_is_not_new():
    assert classify(-1.0, -1.0, False, -2, -1, T) == "best"


def test_losing_own_mate_is_at_least_mistake():
    assert classify(1.0, 0.95, False, 2, None, T) == "mistake"
    assert classify(1.0, 0.0, False, 2, None, T) == "blunder"


def test_keeping_the_mate_is_fine():
    assert classify(1.0, 1.0, False, 2, 4, T) == "best"


def test_mate_rule_skips_already_lost_position():
    assert classify(-0.95, -1.0, False, None, -2, T) == "good"
    assert classify(-0.5, -0.5, False, None, -2, T) == "blunder"
