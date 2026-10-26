from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings as default_settings
from app.main import create_app
from app.openings.lookup import find_opening

REAL_FILE = Path(__file__).resolve().parents[2] / "data" / "openings.tsv"
TSV = (
    "eco\tname\tpgn\n"
    "B00\tKing's Pawn\t1. e4\n"
    "C50\tItalian Game\t1. e4 e5 2. Nf3 Nc6 3. Bc4\n"
    "D30\tQueen's Gambit Declined\t1. d4 d5 2. c4 e6\n"
)


@pytest.fixture
def tsv(tmp_path):
    (tmp_path / "openings.tsv").write_text(TSV, encoding="utf-8")
    return tmp_path


def client_for(tmp_path):
    settings = replace(
        default_settings,
        app_data_dir=tmp_path,
        app_db_path=tmp_path / "app.db",
        puzzles_db_path=tmp_path / "none.db",
        frontend_dist=tmp_path / "dist",
    )
    return TestClient(create_app(settings))


def test_longest_known_opening_wins(tsv):
    path = tsv / "openings.tsv"
    assert find_opening(path, ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4"]) == {
        "eco": "C50",
        "name": "Italian Game",
        "exact": True,
    }
    # moves past the opening keep the last known name
    assert (
        find_opening(path, ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "g8f6"])["name"]
        == "Italian Game"
    )
    assert find_opening(path, ["d2d4", "d7d5", "c2c4", "e7e6"])["eco"] == "D30"
    assert find_opening(path, ["e2e4", "c7c5"]) == {
        "eco": "B00",
        "name": "King's Pawn",
        "exact": False,
    }
    assert find_opening(path, ["a2a3"]) is None
    assert find_opening(path, []) is None


def test_exact_marks_a_book_move(tsv):
    path = tsv / "openings.tsv"
    assert find_opening(path, ["e2e4"])["exact"] is True
    # 1.e4 e5 is not in the file itself: the name is kept, the move is not a book move
    assert find_opening(path, ["e2e4", "e7e5"])["exact"] is False
    assert find_opening(path, ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "g8f6"])["exact"] is False


def test_name_endpoint(tsv):
    c = client_for(tsv)
    r = c.post("/api/openings/name", json={"moves": ["e2e4", "e7e5"]})
    assert r.status_code == 200 and r.json()["eco"] == "B00"
    assert r.json()["exact"] is False
    r = c.post("/api/openings/name", json={"moves": ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4"]})
    assert r.json()["name"] == "Итальянская партия"
    assert c.post("/api/openings/name", json={"moves": ["a2a3"]}).json() is None
    assert c.post("/api/openings/name", json={"moves": ["e2e5"]}).status_code == 422


def test_missing_file_is_503(tmp_path):
    r = client_for(tmp_path).post("/api/openings/name", json={"moves": ["e2e4"]})
    assert r.status_code == 503
    assert "download_openings.py" in r.json()["detail"]


@pytest.mark.skipif(not REAL_FILE.is_file(), reason="run scripts/download_openings.py")
def test_real_file_lines():
    assert (
        find_opening(REAL_FILE, ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4"])["name"] == "Italian Game"
    )
    name = find_opening(REAL_FILE, ["d2d4", "d7d5", "c2c4", "e7e6"])["name"]
    assert name.startswith("Queen's Gambit Declined")
    assert find_opening(REAL_FILE, ["a2a3"])["eco"] == "A00"


ITALIAN = "e2e4 e7e5 g1f3 b8c6 f1c4"
REAL_PUZZLES = REAL_FILE.parent / "puzzles.db"


@pytest.mark.skipif(not REAL_FILE.is_file(), reason="run scripts/download_openings.py")
def test_card_for_the_italian_game(tmp_path):
    settings = replace(
        default_settings,
        app_data_dir=REAL_FILE.parent,
        app_db_path=tmp_path / "app.db",
        puzzles_db_path=REAL_PUZZLES if REAL_PUZZLES.is_file() else tmp_path / "none.db",
        frontend_dist=tmp_path / "dist",
    )
    r = TestClient(create_app(settings)).get("/api/openings/card", params={"moves": ITALIAN})
    assert r.status_code == 200
    card = r.json()
    assert card["name"] == "Итальянская партия" and card["eco"] == "C50"
    assert card["line_san"] == ["e4", "e5", "Nf3", "Nc6", "Bc4"]
    nxt = {x["san"]: x for x in card["continuations"]}
    assert {"Bc5", "Nf6"} <= nxt.keys()
    assert nxt["Bc5"]["uci"] == "f8c5"
    assert len(nxt) == len(card["continuations"]) <= 8
    assert card["lesson"]["slug"] == "italian-game-white"
    assert card["puzzles"] == ("Italian_Game" if REAL_PUZZLES.is_file() else None)


def test_card_small_book(tsv):
    c = client_for(tsv)
    card = c.get("/api/openings/card", params={"moves": "e2e4"}).json()
    assert card["line_san"] == ["e4"]
    assert [x["san"] for x in card["continuations"]] == ["e5"]  # from Italian Game, 2nd ply
    assert card["lesson"] is None and card["puzzles"] is None
    # the game left the book: the last matched opening stays
    out = c.get("/api/openings/card", params={"moves": ITALIAN + " g8f6 d2d3"}).json()
    assert out["name"] == "Итальянская партия" and out["continuations"] == []
    assert out["lesson"]["slug"] == "italian-game-white"


def test_card_errors(tsv):
    c = client_for(tsv)
    assert c.get("/api/openings/card", params={"moves": "a2a3"}).status_code == 404
    assert c.get("/api/openings/card").status_code == 404
    assert c.get("/api/openings/card", params={"moves": "e2e5"}).status_code == 422
