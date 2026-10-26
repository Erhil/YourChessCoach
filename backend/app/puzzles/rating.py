"""Elo rating for puzzles. Pure functions."""

START_RATING = 600.0


def expected_score(user_rating: float, puzzle_rating: float) -> float:
    return 1 / (1 + 10 ** ((puzzle_rating - user_rating) / 400))


def k_factor(attempts: int) -> float:
    return max(20, 60 - 2 * attempts)


def score(solved: bool, used_hint: bool) -> float:
    if not solved:
        return 0.0
    return 0.5 if used_hint else 1.0


def update_rating(user_rating: float, attempts: int, puzzle_rating: float, result: float) -> float:
    return user_rating + k_factor(attempts) * (result - expected_score(user_rating, puzzle_rating))
