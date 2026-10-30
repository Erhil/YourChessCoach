import base64
import copy
import json
import shutil

import pytest
from fastapi.testclient import TestClient

from app.coach.explain import current_model
from app.coach.templates import explain
from app.config import settings
from app.db import connect
from app.main import app
from tests.test_validator import facts

BENCH_DIR = settings.app_data_dir / "bench"


def _answer(item_id, valid=True, seconds=1.0):
    return {
        "id": item_id,
        "text": '{"tip":"none"}',
        "display_text": f"text {item_id}",
        "seconds": seconds,
        "valid": valid,
        "reasons": [],
        "cyrillic": 1.0,
    }


def _item(item_id):
    return {
        "id": item_id,
        "kind": "k",
        "fen": "8/8/8/8/8/8/8/K6k w - - 0 1",
        "move_uci": "a1a2",
        "facts": facts(
            player_move={"san": "Ka2", "uci": "a1a2"},
            best_move={"san": "Kb1", "uci": "a1b1"},
        ).model_dump(),
    }


BENCH = {
    "created": "2026-01-01T00:00:00",
    "items": [_item("i1"), _item("i2")],
    "results": {
        "m1": {"vram_gb": 3.0, "answers": [_answer("i1", seconds=1), _answer("i2", False, 3)]},
        "m2": {"vram_gb": 4.0, "answers": [_answer("i1", seconds=2), _answer("i2", False, 3)]},
        "template": {
            "vram_gb": None,
            "answers": [_answer("i1", seconds=0), _answer("i2", seconds=0)],
        },
    },
}


@pytest.fixture
def client():
    shutil.rmtree(BENCH_DIR, ignore_errors=True)
    with TestClient(app) as c:
        r = c.post("/api/admin/login", json={"token": settings.admin_token})
        assert r.status_code == 200
        yield c
    shutil.rmtree(BENCH_DIR, ignore_errors=True)


def _write(data=BENCH):
    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    (BENCH_DIR / "20260101-000000.json").write_text(json.dumps(data), encoding="utf-8")


def test_no_results_file(client):
    for method, url in [("get", "/api/admin/bench/pair"), ("get", "/api/admin/bench/results")]:
        r = getattr(client, method)(url)
        assert r.status_code == 404
        assert r.json()["detail"].startswith("Нет результатов сравнения")


def test_pair_hides_model_names(client):
    _write()
    r = client.get("/api/admin/bench/pair")
    assert r.status_code == 200
    body = r.json()
    assert body["item_id"] == "i1"  # i2 has no two valid answers
    assert body["move_san"] == "Ka2"
    assert body["best_move_san"] == "Kb1"
    assert body["classification"] == "blunder"
    assert {body["a"]["text"], body["b"]["text"]} == {
        explain(
            facts(
                player_move={"san": "Ka2", "uci": "a1a2"}, best_move={"san": "Kb1", "uci": "a1b1"}
            )
        )
    }
    assert set(body["a"]) == {"text"}
    assert "m1" not in json.dumps({k: v for k, v in body.items() if k != "token"})


def test_vote_and_results(client):
    _write()
    token = client.get("/api/admin/bench/pair").json()["token"]
    _, a, b = json.loads(base64.urlsafe_b64decode(token))
    r = client.post("/api/admin/bench/vote", json={"token": token, "winner": "a"})
    assert r.json() == {"votes": 1}
    client.post("/api/admin/bench/vote", json={"token": token, "winner": "tie"})
    res = client.get("/api/admin/bench/results").json()
    by = {m["model"]: m for m in res["models"]}
    assert (by[a]["wins"], by[a]["ties"], by[a]["votes"]) == (1, 1, 2)
    assert (by[b]["losses"], by[b]["ties"]) == (1, 1)
    assert by[a]["win_rate"] == 0.5
    assert by["m1"]["valid_pct"] == 0.5
    assert by["m1"]["mean_seconds"] == 2
    assert by["m2"]["vram_gb"] == 4.0
    assert res["models"][0]["model"] == a
    assert res["bench_created"] == BENCH["created"]


def test_bad_vote_is_rejected(client):
    _write()
    assert (
        client.post("/api/admin/bench/vote", json={"token": "xx", "winner": "a"}).status_code == 422
    )
    bad = base64.urlsafe_b64encode(json.dumps(["i1", "m1", "nope"]).encode()).decode()
    assert (
        client.post("/api/admin/bench/vote", json={"token": bad, "winner": "a"}).status_code == 422
    )
    token = client.get("/api/admin/bench/pair").json()["token"]
    assert (
        client.post("/api/admin/bench/vote", json={"token": token, "winner": "x"}).status_code
        == 422
    )


def test_default_model(client):
    _write()
    assert client.post("/api/admin/bench/default", json={"model": "nope"}).status_code == 422
    assert client.post("/api/admin/bench/default", json={"model": "m2"}).status_code == 200
    assert client.get("/api/admin/bench/results").json()["default_model"] == "m2"
    db = connect(settings.app_db_path)
    try:
        assert current_model(db, settings) == "m2"
    finally:
        db.close()
    assert client.post("/api/admin/bench/default", json={"model": "template"}).status_code == 200
    assert client.get("/api/admin/bench/results").json()["default_model"] == "template"
    assert client.post("/api/admin/bench/default", json={"model": "m1"}).status_code == 200
    assert client.get("/api/admin/bench/results").json()["default_model"] == "m1"


def test_saved_prose_is_not_served_even_when_marked_valid(client):
    data = copy.deepcopy(BENCH)
    for result in data["results"].values():
        for answer in result["answers"]:
            answer.update(text="После Qh4 вы выигрываете ферзя.", valid=True)
    _write(data)
    # The template is the only safe model; it cannot form a comparison pair alone.
    assert client.get("/api/admin/bench/pair").status_code == 404
