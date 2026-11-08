import sqlite3
from contextlib import closing
from dataclasses import replace

import chess
import pytest
from fastapi.testclient import TestClient

from app.auth import service
from app.config import settings as default_settings
from app.db import connect
from app.engines.pool import EngineUnavailableError
from app.main import create_app
from app.progress import training

FEN = "rn3rk1/1pp2ppp/1b6/pP2p1q1/P7/2PPPP1P/R2NK3/3Q1B1R w - - 3 16"
MIRRORED = chess.Board(FEN).mirror().fen()
URL = "/api/training"
LOGIN = {"expected_login": "tester"}


def make_settings(tmp_path, puzzles):
    path = tmp_path / "puzzles.db"
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript(
            """
            CREATE TABLE puzzles (id TEXT PRIMARY KEY, fen TEXT, moves TEXT, rating INTEGER, themes TEXT);
            CREATE TABLE puzzle_themes (puzzle_id TEXT, theme TEXT);
            """
        )
        db.executemany("INSERT INTO puzzles VALUES (?, ?, ?, ?, ?)", puzzles)
        db.executemany("INSERT INTO puzzle_themes VALUES (?, ?)", ((p[0], p[4]) for p in puzzles))
    return replace(
        default_settings,
        app_db_path=tmp_path / "app.db",
        puzzles_db_path=path,
        backup_dir=tmp_path / "backups",
        llm_enabled=False,
    )


def start(client, key="start", kind="practice"):
    return client.post(f"{URL}/start", json={**LOGIN, "kind": kind, "client_id": key})


def act(client, session, name, key=None, **fields):
    return client.post(
        f"{URL}/{session['id']}/action",
        json={
            **LOGIN,
            "version": session["version"],
            "action": name,
            "client_id": key or name,
            **fields,
        },
    )


def save_game(client):
    pgn = f'[SetUp "1"]\n[FEN "{FEN}"]\n\n16. Ne4 Qg3+ *'
    saved = client.post(
        "/api/games",
        json={
            "pgn": pgn,
            "result": "*",
            "player_color": "black",
            "errors": [
                {"ply": 2, "best_uci": "g5e3", "classification": "mistake", "motif": "mateIn1"}
            ],
        },
    )
    assert saved.status_code == 201, saved.text


class Offline:
    def analyse(self, *args, **kwargs):
        raise EngineUnavailableError("offline")


class MateEngine:
    def analyse(self, board, depth, multipv=1):
        for move in board.legal_moves:
            after = board.copy()
            after.push(move)
            if after.is_checkmate():
                return depth, [
                    {
                        "score": {"cp": None, "mate": 1 if board.turn else -1},
                        "pv_uci": [move.uci()],
                        "pv_san": [board.san(move)],
                    }
                ]
        raise AssertionError("Expected a mate in one")


def test_restart_and_retry_preserve_first_move_owner_and_partial_result(tmp_path, monkeypatch):
    settings = make_settings(tmp_path, [("first", FEN, "d2e4 g5e3", 600, "mateIn1")])
    app = create_app(settings)
    monkeypatch.setattr(app.state, "pool", Offline())
    client = TestClient(app)
    first = start(client).json()
    assert first["total"] == 1 and first["position"]["novelty"] == "new"
    assert "theme" not in str(first) and first["feedback"] is None
    assert act(client, first, "move", uci="g5h8").status_code == 422
    hinted = act(client, first, "hint").json()
    assert hinted["position"]["hint"]
    assert act(client, hinted, "move", uci="g5e3").status_code == 503
    assert client.get(URL).json()["session"] == hinted
    client.close()

    restarted = create_app(settings)
    monkeypatch.setattr(restarted.state, "pool", MateEngine())
    client = TestClient(restarted)
    assert start(client).json() == hinted
    result = act(client, hinted, "move", uci="g5e3").json()
    assert result["feedback"]["correct"] and result["feedback"]["played_uci"] == "g5e3"
    assert result["counts"]["assisted"] == {"answered": 1, "correct": 1}
    assert result["counts"]["independent"] == {"answered": 0, "correct": 0}
    assert act(client, hinted, "move", uci="g5e3").json() == result
    assert act(client, hinted, "move", uci="g5g3").status_code == 409
    assert act(client, hinted, "finish", key="stale").status_code == 409
    done = act(client, result, "finish").json()
    assert done["state"] == "done" and done["counts"] == result["counts"]
    assert act(client, hinted, "move", uci="g5e3").json() == done

    with closing(connect(settings.app_db_path)) as db:
        service.create_user(db, "other", "aaaa-bbbb-cccc-dddd")
    assert (
        client.post(
            "/api/auth/login", json={"login": "other", "token": "aaaa-bbbb-cccc-dddd"}
        ).status_code
        == 200
    )
    assert client.get(URL, params=LOGIN).status_code == 403
    assert act(client, result, "finish").status_code == 403
    assert act(client, result, "finish", expected_login="other").status_code == 404
    assert client.get(URL).json()["session"] is None


def test_delayed_check_uses_seven_day_history_and_excludes_same_position(tmp_path, monkeypatch):
    duplicate = FEN.rsplit(" ", 2)[0] + " 0 21"
    settings = make_settings(
        tmp_path,
        [
            ("first", FEN, "d2e4 g5e3", 600, "mateIn1"),
            ("same", duplicate, "d2e4 g5e3", 601, "mateIn1"),
            ("wrong-theme", MIRRORED, "d7e5 g4e6", 602, "fork"),
        ],
    )
    now = 1800000000
    monkeypatch.setattr(training, "time", lambda: now)
    app = create_app(settings)
    monkeypatch.setattr(app.state, "pool", MateEngine())
    with TestClient(app) as client:
        practice = start(client).json()
        solved = act(client, practice, "move", uci="g5e3").json()
        assert act(client, solved, "next").json()["state"] == "done"
        now += 7 * training.DAY - 1
        assert client.get(URL).json()["delayed_available"] is False
        assert start(client, "delayed", "delayed").status_code == 404
        now += 1
        unavailable = client.get(URL).json()
        assert unavailable["delayed_available"] is False
        assert unavailable["delayed_notice"] == training.NO_DELAYED
        assert start(client, "delayed", "delayed").status_code == 404
        with closing(sqlite3.connect(settings.puzzles_db_path)) as pdb, pdb:
            pdb.execute(
                "INSERT INTO puzzles VALUES ('unseen', ?, 'd7e5 g4e6', 605, 'mateIn1')",
                (MIRRORED,),
            )
            pdb.execute("INSERT INTO puzzle_themes VALUES ('unseen', 'mateIn1')")
        assert client.get(URL).json()["delayed_available"] is True
        delayed = start(client, "delayed", "delayed").json()
        assert delayed["kind"] == "delayed" and delayed["delay_days"] == 7
        assert delayed["difficulty"] == {"min": 605, "max": 605}
        assert delayed["position"]["novelty"] == "new" and delayed["new_positions"] == 1
        assert "hint" not in delayed["position"] and "theme" not in str(delayed)
        assert act(client, delayed, "hint", key="late-hint").status_code == 409
        revealed = act(client, delayed, "reveal").json()
        assert revealed["feedback"]["line"][0] == "g4e6"
        assert revealed["counts"]["unfinished"] == 1
        assert revealed["counts"]["assisted"]["answered"] == 0


def test_early_finish_keeps_unopened_exercise_eligible(tmp_path):
    settings = make_settings(tmp_path, [("only", MIRRORED, "d7e5 g4e6", 605, "mateIn1")])
    with TestClient(create_app(settings)) as client:
        save_game(client)
        first = start(client).json()
        assert first["position"]["source"] == "game" and first["total"] == 2
        done = act(client, first, "finish").json()
        assert done["state"] == "done"
        assert done["counts"]["assigned"] == done["counts"]["unfinished"] == 2
        assert done["new_positions"] == 0 and done["difficulty"] is None

        again = start(client, "again").json()
        assert again["total"] == 2 and again["notice"] is None
        assert again["new_positions"] == 0 and again["difficulty"] is None


def test_training_starts_with_newest_saved_game_despite_late_error_delivery(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, []))) as client:
        old = {"client_id": "older", "pgn": "1. d4 d5 *", "result": "*", "player_color": "white"}
        assert client.post("/api/games", json=old).status_code == 201
        assert (
            client.post(
                "/api/games",
                json={
                    **old,
                    "client_id": "newer",
                    "pgn": "1. e4 e5 2. Nf3 Nc6 *",
                    "errors": [{"ply": 3, "best_uci": "f1c4", "classification": "mistake"}],
                },
            ).status_code
            == 201
        )
        assert (
            client.post(
                "/api/games",
                json={
                    **old,
                    "errors": [{"ply": 1, "best_uci": "e2e4", "classification": "mistake"}],
                },
            ).status_code
            == 201
        )
        position = start(client).json()["position"]
        board = chess.Board()
        board.push_san("e4")
        board.push_san("e5")
        assert position["source"] == "game" and position["fen"] == board.fen()


@pytest.mark.engine
@pytest.mark.parametrize(
    ("source_fen", "puzzle_move", "played", "mate", "accepted"),
    [
        ("1k6/8/1QK5/8/8/8/8/8 b - - 0 1", "b6b7", "b6b2", 1, False),
        ("1k6/8/1QK5/8/8/8/8/8 b - - 0 1", "b6b7", "b6b7", 1, True),
        ("1k6/8/2KQ4/8/8/8/8/8 b - - 0 1", "d6b4", "d6a3", 2, False),
        ("1k6/8/2KQ4/8/8/8/8/8 b - - 0 1", "d6b4", "d6d7", 2, True),
    ],
)
def test_exercise_requires_shortest_mate(tmp_path, source_fen, puzzle_move, played, mate, accepted):
    settings = make_settings(tmp_path, [("mate", source_fen, f"b8a8 {puzzle_move}", 600, "mate")])
    with TestClient(create_app(replace(settings, coach_depth=14))) as client:
        first = start(client).json()
        response = act(client, first, "move", uci=played)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["counts"]["independent"] == {"answered": 1, "correct": int(accepted)}
        feedback = result["feedback"]
        assert feedback["correct"] is accepted
        assert (feedback["line"][0] == played) is accepted
        if not accepted:
            board = chess.Board(first["position"]["fen"])
            assert f"Мат в {mate}" in feedback["text"]
            for move in feedback["line"]:
                board.push_uci(move)
            assert len(feedback["line"]) == 2 * mate - 1 and board.is_checkmate()


@pytest.mark.engine
def test_saved_game_to_distinct_exercise_uses_stockfish_and_leaves_ratings_unchanged(tmp_path):
    settings = make_settings(
        tmp_path,
        [
            ("known", FEN, "d2e4 g5e3", 600, "mateIn1"),
            ("new", MIRRORED, "d7e5 g4e6", 605, "mateIn1"),
        ],
    )
    with TestClient(create_app(settings)) as client:
        save_game(client)
        cards = client.get("/api/mistakes/stats").json()
        rating = client.get("/api/puzzles/rating").json()
        first = start(client).json()
        assert first["total"] == 2 and first["position"]["source"] == "game"
        assert "g5g3" not in str(first) and "g5e3" not in str(first)
        feedback = act(client, first, "move", uci="g5e3")
        assert feedback.status_code == 200, feedback.text
        solved = feedback.json()
        assert solved["feedback"]["correct"]
        assert solved["feedback"]["original_uci"] == "g5g3"
        assert solved["feedback"]["original_text"]
        exercise = act(client, solved, "next").json()
        assert exercise["position"]["rating"] == 605
        assert exercise["new_positions"] == 1 and exercise["difficulty"] == {"min": 605, "max": 605}
        assert exercise["feedback"] is None
        done = act(client, exercise, "finish").json()
        assert done["counts"] == {
            "assigned": 2,
            "independent": {"answered": 1, "correct": 1},
            "assisted": {"answered": 0, "correct": 0},
            "unfinished": 1,
        }
        assert client.get("/api/mistakes/stats").json() == cards
        assert client.get("/api/puzzles/rating").json() == rating
        personal_only = start(client, "again").json()
        assert personal_only["total"] == 1 and personal_only["notice"] == training.NO_EXERCISE
