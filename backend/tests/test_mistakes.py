import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Barrier
from types import SimpleNamespace

import chess
import pytest
from fastapi.testclient import TestClient
from test_puzzles import build_puzzles_db

from app.config import settings as default_settings
from app.db import MIGRATIONS, migrate
from app.main import create_app
from app.mistakes.srs import schedule

MATE_GAME = "1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7#"
# White mates with Ra8#; Ra3 throws the win away.
BACK_RANK = "6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1"
NOW = "2026-01-01T00:00:00Z"


@pytest.fixture
def client(tmp_path):
    pdb = tmp_path / "puzzles.db"
    build_puzzles_db(pdb)
    settings = replace(
        default_settings,
        app_db_path=tmp_path / "app.db",
        puzzles_db_path=pdb,
        frontend_dist=tmp_path / "dist",
    )
    with TestClient(create_app(settings)) as c:
        c.db_path = settings.app_db_path
        yield c


def play_card(client, fen=BACK_RANK, best="a1a8", classification="blunder"):
    body = {"source": "play", "fen": fen, "best_uci": best, "classification": classification}
    return client.post("/api/mistakes", json=body)


def test_schedule_right_answers_in_a_row():
    assert schedule(0, True, NOW) == (1, "2026-01-02T00:00:00Z", False)
    assert schedule(1, True, NOW) == (2, "2026-01-04T00:00:00Z", False)
    assert schedule(2, True, NOW) == (3, "2026-01-08T00:00:00Z", True)


def test_schedule_wrong_answer_resets_and_stays_due_today():
    assert schedule(2, False, NOW) == (0, NOW, False)
    assert schedule(0, False, NOW) == (0, NOW, False)


def test_learned_card_returns_when_due_and_is_counted(client):
    a = play_card(client).json()["id"]
    b = play_card(client, fen=chess.STARTING_FEN, best="e2e4", classification="mistake").json()[
        "id"
    ]
    conn = sqlite3.connect(client.db_path)
    conn.execute("UPDATE mistakes SET due_at = '2020-01-01T00:00:00Z' WHERE id = ?", (a,))
    conn.execute(
        "UPDATE mistakes SET learned_at = '2026-01-01T00:00:00Z', streak = 3,"
        " due_at = '2019-01-01T00:00:00Z' WHERE id = ?",
        (b,),
    )
    conn.commit()
    conn.row_factory = sqlite3.Row
    from app.mcp.tools import _mistakes_block

    user = conn.execute("SELECT id FROM users").fetchone()[0]
    assert _mistakes_block(SimpleNamespace(db=conn, user_id=user))["due"] == 2
    conn.close()
    assert client.get("/api/mistakes/next").json()["card"]["id"] == b
    assert client.get("/api/mistakes/stats").json() == {"total": 2, "due": 2, "learned": 1}
    assert client.get("/api/progress").json()["mistakes"] == {"total": 2, "due": 2, "learned": 1}


def test_migration_keeps_old_cards_with_streak_zero(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    for number, script in enumerate(MIGRATIONS[:6], start=1):
        conn.executescript("BEGIN;" + script + f"PRAGMA user_version = {number}; COMMIT;")
    conn.execute(
        "INSERT INTO mistakes (source, ref, fen, best_uci, best_san, created_at, box, due_at,"
        " reviews, lapses) VALUES ('play', 'x', 'f', 'e2e4', 'e4', 'n', 4, '2099-01-01T00:00:00Z',"
        " 5, 1)"
    )
    conn.commit()
    conn.close()
    migrate(path)
    conn = sqlite3.connect(path)
    row = conn.execute(
        "SELECT streak, learned_at, reviews, lapses, due_at FROM mistakes"
    ).fetchone()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(mistakes)")]
    conn.close()
    assert row == (0, None, 5, 1, "2099-01-01T00:00:00Z")
    assert "box" not in cols
    assert "played_uci" in cols


def test_play_card_dedupe_and_validation(client):
    first = play_card(client).json()
    assert first["created"] is True
    again = play_card(client).json()
    assert again == {"id": first["id"], "created": False}
    assert client.get("/api/mistakes/stats").json()["total"] == 1
    assert play_card(client, fen="not a fen").status_code == 422
    assert play_card(client, best="a1b3").status_code == 422


def test_play_card_keeps_the_played_move(client):
    body = {"source": "play", "fen": BACK_RANK, "best_uci": "a1a8", "classification": "blunder"}
    assert client.post("/api/mistakes", json={**body, "played_uci": "a1a9"}).status_code == 422
    assert client.post("/api/mistakes", json={**body, "played_uci": "a1b3"}).status_code == 422
    assert client.post("/api/mistakes", json={**body, "played_uci": "a1a3"}).status_code == 200
    assert client.get("/api/mistakes/next").json()["card"]["played_san"] == "Ra3"


def test_card_without_played_move(client):
    play_card(client)  # an older client sends no played_uci
    assert client.get("/api/mistakes/next").json()["card"]["played_san"] is None


def test_next_order_and_due_count(client):
    a = play_card(client).json()["id"]
    b = play_card(client, fen=chess.STARTING_FEN, best="e2e4", classification="mistake").json()[
        "id"
    ]
    conn = sqlite3.connect(client.db_path)
    conn.execute("UPDATE mistakes SET due_at = '2020-01-01T00:00:00Z' WHERE id = ?", (b,))
    conn.execute("UPDATE mistakes SET due_at = '2099-01-01T00:00:00Z' WHERE id = ?", (a,))
    conn.commit()
    data = client.get("/api/mistakes/next").json()
    assert data["due"] == 1 and data["card"]["id"] == b
    assert data["card"]["side"] == "white" and data["card"]["source"] == "play"
    conn.execute("UPDATE mistakes SET due_at = '2099-01-01T00:00:00Z' WHERE id = ?", (b,))
    conn.commit()
    conn.close()
    assert client.get("/api/mistakes/next").json() == {
        "card": None,
        "due": 0,
        "today": {"reviewed": 0, "limit": 10},
    }


def test_failed_puzzle_adds_one_card(client):
    r = client.post("/api/puzzles/yZXbn/attempt", json={"solved": False})
    assert r.status_code == 200
    client.post("/api/puzzles/yZXbn/attempt", json={"solved": False})
    client.post("/api/puzzles/p00/attempt", json={"solved": True})
    stats = client.get("/api/mistakes/stats").json()
    assert stats["total"] == 1
    card = client.get("/api/mistakes/next").json()["card"]
    assert card["side"] == "black" and card["motif"] == "mate"
    board = chess.Board(card["fen"])  # the position after the opponent's first move d2e4
    assert chess.Move.from_uci("g5e3") in board.legal_moves


def test_answer_unknown_card_is_404(client):
    assert client.post("/api/mistakes/999/answer", json={"uci": "a1a8"}).status_code == 404


def test_answer_writes_a_card_review(client, monkeypatch):
    # The right move is known without the engine; a fake stands in for the engine facts.
    fake = SimpleNamespace(classification="best")
    monkeypatch.setattr("app.mistakes.routes.build_facts", lambda *a: fake)
    card_id = play_card(client).json()["id"]
    assert client.post(f"/api/mistakes/{card_id}/answer", json={"uci": "a1a8"}).json()["correct"]
    conn = sqlite3.connect(client.db_path)
    rows = conn.execute(
        "SELECT user_id, mistake_id, correct, created_at FROM card_reviews"
    ).fetchall()
    user = conn.execute("SELECT id FROM users").fetchone()[0]
    conn.close()
    assert [r[:3] for r in rows] == [(user, card_id, 1)]
    assert rows[0][3].endswith("Z") and len(rows[0][3]) == 20


@pytest.mark.parametrize(
    ("classification", "correct"),
    [("best", True), ("good", True), ("inaccuracy", False), ("mistake", False)],
)
def test_answer_other_than_the_saved_best(client, monkeypatch, classification, correct):
    # Ra7 is not the saved best move Ra8#; the fake engine class decides the answer.
    fake = SimpleNamespace(classification=classification)
    monkeypatch.setattr("app.mistakes.routes.build_facts", lambda *a: fake)
    monkeypatch.setattr("app.mistakes.routes.explain_facts", lambda *a: None)
    card_id = play_card(client).json()["id"]
    r = client.post(f"/api/mistakes/{card_id}/answer", json={"uci": "a1a7"}).json()
    assert r["correct"] is correct and r["streak"] == int(correct)


@pytest.mark.engine
def test_good_opening_move_is_a_right_answer(client):
    # 2.d3 after 1.e4 e5 is a bit weaker than the saved 2.Nf3, but it is not a mistake.
    # At depth 14 the engine says "good" (drop 0.048 on 2026-10-25); "best" is also right.
    fen = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"
    card_id = play_card(client, fen=fen, best="g1f3", classification="mistake").json()["id"]
    r = client.post(f"/api/mistakes/{card_id}/answer", json={"uci": "d2d3"}).json()
    assert r["correct"] and r["best_san"] == "Nf3"


@pytest.mark.engine
def test_wrong_answer_resets_and_card_stays_due(client):
    card_id = play_card(client).json()["id"]
    url = f"/api/mistakes/{card_id}/answer"
    assert client.post(f"/api/mistakes/{card_id}/answer", json={"uci": "a1a0"}).status_code == 422
    ok = client.post(url, json={"uci": "a1a8"}).json()
    assert ok["correct"] and ok["streak"] == 1 and ok["left"] == 2 and not ok["learned"]
    assert ok["best_san"] == "Ra8#" and ok["explanation"] is None and ok["due_at"] > "2026"
    assert client.get("/api/mistakes/next").json()["card"] is None  # next review is tomorrow
    conn = sqlite3.connect(client.db_path)
    conn.execute("UPDATE mistakes SET due_at = '2020-01-01T00:00:00Z'")
    conn.commit()
    conn.close()
    bad = client.post(url, json={"uci": "a1a3", "review_version": 1}).json()
    assert not bad["correct"] and bad["streak"] == 0 and bad["left"] == 3 and bad["explanation"]
    # The wrong answer keeps the card due now: it is the next card, and it is counted as due.
    data = client.get("/api/mistakes/next").json()
    assert data["card"]["id"] == card_id and data["due"] == 1
    conn = sqlite3.connect(client.db_path)
    assert conn.execute("SELECT reviews, lapses FROM mistakes").fetchone() == (2, 1)
    conn.close()


@pytest.mark.engine
def test_third_right_answer_in_a_row_marks_card_learned(client):
    card_id = play_card(client).json()["id"]
    url = f"/api/mistakes/{card_id}/answer"
    conn = sqlite3.connect(client.db_path)
    for expected in (1, 2):
        r = client.post(url, json={"uci": "a1a8", "review_version": expected - 1}).json()
        assert r["streak"] == expected and not r["learned"]
        conn.execute("UPDATE mistakes SET due_at = '2020-01-01T00:00:00Z'")
        conn.commit()
    client.post(
        url, json={"uci": "a1a3", "review_version": 2}
    )  # a wrong answer starts the count again
    conn.execute("UPDATE mistakes SET due_at = '2020-01-01T00:00:00Z'")
    conn.commit()
    for version in (3, 4):
        client.post(url, json={"uci": "a1a8", "review_version": version})
        conn.execute("UPDATE mistakes SET due_at = '2020-01-01T00:00:00Z'")
        conn.commit()
    assert client.get("/api/mistakes/next").json()["card"]["id"] == card_id
    last = client.post(url, json={"uci": "a1a8", "review_version": 5}).json()
    conn.close()
    assert last["learned"] and last["left"] == 0 and last["streak"] == 3
    assert client.get("/api/mistakes/next").json() == {
        "card": None,
        "due": 0,
        "today": {"reviewed": 6, "limit": 10},  # six deck answers today
    }
    assert client.get("/api/mistakes/stats").json() == {"total": 1, "due": 0, "learned": 1}


@pytest.mark.engine
def test_review_of_saved_game_adds_cards(client):
    body = {"pgn": MATE_GAME, "player_color": "black", "result": "1-0"}
    gid = client.post("/api/games", json=body).json()["id"]
    assert client.post("/api/review", json={"game_id": gid}).status_code == 200
    stats = client.get("/api/mistakes/stats").json()
    assert stats["total"] >= 1
    total = stats["total"]
    conn = sqlite3.connect(client.db_path)
    played = {r[0] for r in conn.execute("SELECT played_uci FROM mistakes")}
    conn.close()
    assert "g8f6" in played  # 3...Nf6 allows 4.Qxf7#: the card keeps this move
    client.post("/api/review", json={"game_id": gid})
    assert client.get("/api/mistakes/stats").json()["total"] == total


def add_reviews(client, user, stamps):
    conn = sqlite3.connect(client.db_path)
    with conn:
        conn.executemany(
            "INSERT INTO card_reviews (user_id, mistake_id, created_at, correct) VALUES (?, 1, ?, 1)",
            [(user, ts) for ts in stamps],
        )
    conn.close()


def test_daily_limit_by_local_day_and_user(client, monkeypatch):
    now = {"t": "2026-10-21T12:00:00Z"}
    monkeypatch.setattr("app.mistakes.routes.now_utc", lambda: now["t"])
    card_id = play_card(client).json()["id"]
    conn = sqlite3.connect(client.db_path)
    with conn:
        user = conn.execute("SELECT id FROM users").fetchone()[0]
        other = conn.execute(
            "INSERT INTO users (login, token_hash, created_at) VALUES ('other', 'x', 'n')"
        ).lastrowid
    conn.close()
    # 9 answers on 10-21 in Moscow; 22:30Z on 10-20 is 01:30 on 10-21 there.
    add_reviews(client, user, ["2026-10-20T22:30:00Z"] + ["2026-10-21T08:00:00Z"] * 8)
    add_reviews(client, user, ["2026-10-20T20:00:00Z"])  # 23:00 on 10-20 in Moscow
    add_reviews(client, other, ["2026-10-21T08:00:00Z"] * 5)

    def get(tz=-180):
        r = client.get("/api/mistakes/next", params={"tz": tz})
        assert r.status_code == 200, r.text
        return r.json()

    data = get()
    assert data["card"]["id"] == card_id and data["today"] == {"reviewed": 9, "limit": 10}
    add_reviews(client, user, ["2026-10-21T09:00:00Z"])
    assert get() == {"card": None, "due": 1, "today": {"reviewed": 10, "limit": 10}}
    # In UTC the 22:30Z answer is on 10-20, so only 9 answers are on 10-21.
    assert get(tz=0)["card"]["id"] == card_id
    # 21:30Z is 00:30 on 10-22 in Moscow: a new local day gives cards again.
    now["t"] = "2026-10-21T21:30:00Z"
    data = get()
    assert data["card"]["id"] == card_id and data["today"]["reviewed"] == 0


@pytest.mark.parametrize("tz", [-841, 841, "x"])
def test_next_tz_validation(client, tz):
    assert client.get("/api/mistakes/next", params={"tz": tz}).status_code == 422


def test_replay_cannot_advance_or_skip_a_review(client, monkeypatch):
    monkeypatch.setattr(
        "app.mistakes.routes.build_facts", lambda *a: SimpleNamespace(classification="best")
    )
    card_id = play_card(client).json()["id"]
    url = f"/api/mistakes/{card_id}/answer"
    assert client.post(url, json={"uci": "a1a8", "review_version": 0}).status_code == 200
    assert client.post(url, json={"uci": "a1a8", "review_version": 0}).status_code == 409
    assert client.post(url, json={"uci": "a1a8", "review_version": 1}).status_code == 409
    conn = sqlite3.connect(client.db_path)
    assert conn.execute("SELECT streak, reviews FROM mistakes").fetchone() == (1, 1)
    conn.close()


def test_retention_intervals_are_bounded_and_lapse_restarts_learning():
    assert schedule(3, True, NOW) == (4, "2026-01-15T00:00:00Z", True)
    assert schedule(4, True, NOW) == (5, "2026-01-31T00:00:00Z", True)
    assert schedule(100, True, NOW) == (101, "2026-03-02T00:00:00Z", True)
    assert schedule(5, False, NOW) == (0, NOW, False)


def test_simultaneous_answers_record_one_review(client, monkeypatch):
    # Both requests read version zero before either engine call completes.
    barrier = Barrier(2)

    def facts(*args):
        barrier.wait(timeout=10)
        return SimpleNamespace(classification="best")

    monkeypatch.setattr("app.mistakes.routes.build_facts", facts)
    card_id = play_card(client).json()["id"]
    url = f"/api/mistakes/{card_id}/answer"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: client.post(url, json={"uci": "a1a8", "review_version": 0}), range(2)
            )
        )
    assert sorted(r.status_code for r in results) == [200, 409]
    assert client.post(url, json={"uci": "a1a8", "review_version": 0}).status_code == 409
    conn = sqlite3.connect(client.db_path)
    assert conn.execute("SELECT reviews, streak FROM mistakes").fetchone() == (1, 1)
    assert conn.execute("SELECT COUNT(*) FROM card_reviews").fetchone()[0] == 1
    conn.close()


def test_legacy_learned_cards_keep_milestone_and_receive_future_due_date(tmp_path):
    path = tmp_path / "legacy-learned.db"
    conn = sqlite3.connect(path)
    # Build the deployed schema before the retention migration.
    for number, script in enumerate(MIGRATIONS[:14], start=1):
        conn.executescript("BEGIN;" + script + f"PRAGMA user_version = {number}; COMMIT;")
    user = conn.execute(
        "INSERT INTO users (login, token_hash, created_at) VALUES ('legacy', 'x', 'n')"
    ).lastrowid
    conn.execute(
        "INSERT INTO mistakes (user_id, source, ref, fen, best_uci, best_san, created_at, due_at, "
        "reviews, lapses, streak, learned_at) VALUES (?, 'play', 'old', ?, 'a1a8', 'Ra8#', "
        "'2020-01-01T00:00:00Z', '2020-01-02T00:00:00Z', 5, 1, 3, '2020-01-03T00:00:00Z')",
        (user, BACK_RANK),
    )
    conn.commit()
    conn.close()
    before = datetime.now(UTC)
    migrate(path)
    conn = sqlite3.connect(path)
    row = conn.execute(
        "SELECT reviews, lapses, streak, learned_at, due_at FROM mistakes"
    ).fetchone()
    assert row[:4] == (5, 1, 3, "2020-01-03T00:00:00Z")
    due = datetime.fromisoformat(row[4])
    assert before + timedelta(days=7) <= due <= datetime.now(UTC) + timedelta(days=60)
    migrate(path)
    assert conn.execute("SELECT due_at FROM mistakes").fetchone()[0] == row[4]
    conn.close()
