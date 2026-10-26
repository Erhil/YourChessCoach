"""Mistakes deck: a card is learned after 3 right answers in a row; a wrong answer resets the count."""

from datetime import UTC, datetime, timedelta

LEARNED_STREAK = 3
# Deck answers in one local day; after them /next gives no card until the next local day.
DAILY_LIMIT = 10
# Days until the next review, by the count of right answers in a row (the 3rd one ends the review).
INTERVAL_DAYS = {1: 1, 2: 3}
FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def now_utc() -> str:
    return datetime.now(UTC).strftime(FORMAT)


def schedule(streak: int, correct: bool, now: str | None = None) -> tuple[int, str, bool]:
    """Return (new streak, due_at, learned) for an answer given at `now` (UTC string).

    A wrong answer sets the streak to 0 and keeps the card due now, so it comes back after the
    other due cards (the queue is ordered by due_at).
    """
    now = now or now_utc()
    if not correct:
        return 0, now, False
    new_streak = streak + 1
    if new_streak >= LEARNED_STREAK:
        return new_streak, now, True
    due = datetime.strptime(now, FORMAT) + timedelta(days=INTERVAL_DAYS[new_streak])
    return new_streak, due.strftime(FORMAT), False
