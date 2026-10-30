"""Blind pairwise comparison of LLM models over a saved bench results file."""

import base64
import binascii
import json
import math
import random
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.coach.explain import current_model
from app.coach.schema import CoachFacts
from app.coach.templates import explain
from app.coach.validator import render_response
from app.db import Db

router = APIRouter(prefix="/api/admin/bench")

NO_RESULTS = "Нет результатов сравнения. Запустите python scripts/bench_models.py"


def load_bench(request: Request) -> dict:
    files = sorted((request.app.state.settings.app_data_dir / "bench").glob("*.json"))
    for path in reversed(files):
        try:
            bench = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            raise HTTPException(500, f"Не удалось прочитать отчёт {path.name}") from exc
        if (
            isinstance(bench, dict)
            and "items" not in bench
            and "created" not in bench
            and all(key in bench for key in ("machine", "hardware", "inputs"))
        ):
            continue  # Runtime benchmark reports also have a results map.
        # Other tools also wrote reports here. Model reports use items and a model map.
        # A partial model report is an error, not a reason to use stale results.
        if isinstance(bench, dict) and (
            "items" in bench or "created" in bench or isinstance(bench.get("results"), dict)
        ):
            if not (
                isinstance(bench.get("items"), list)
                and isinstance(bench.get("results"), dict)
                and isinstance(bench.get("created"), str)
            ):
                raise HTTPException(500, f"Неверный формат отчёта сравнения {path.name}")
            break
    else:
        raise HTTPException(404, NO_RESULTS)
    try:
        facts = {}
        for item in bench["items"]:
            if not isinstance(item["id"], str) or not isinstance(item["fen"], str):
                raise TypeError("invalid item")
            facts[item["id"]] = CoachFacts.model_validate(item["facts"])
            item["facts"] = facts[item["id"]].model_dump()
        for model, result in bench["results"].items():
            if not isinstance(result["answers"], list):
                raise TypeError("invalid answers")
            for answer in result["answers"]:
                if (
                    not isinstance(answer["id"], str)
                    or not isinstance(answer["valid"], bool)
                    or type(answer["seconds"]) not in (int, float)
                    or not math.isfinite(answer["seconds"])
                    or (model != "template" and not isinstance(answer["text"], str))
                ):
                    raise ValueError("invalid answer")
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(500, f"Неверный формат отчёта сравнения {path.name}") from exc
    for model, result in bench["results"].items():
        for answer in result["answers"]:
            try:
                f = facts[answer["id"]]
                answer["display_text"] = (
                    explain(f) if model == "template" else render_response(answer["text"], f)
                )
            except (ValueError, KeyError):
                answer["valid"] = False
                answer["display_text"] = ""
    return bench


def _answer(bench: dict, model: str, item_id: str) -> dict | None:
    answers = bench["results"].get(model, {}).get("answers", [])
    return next((a for a in answers if a["id"] == item_id), None)


@router.get("/pair")
def pair(request: Request) -> dict:
    bench = load_bench(request)
    options = []
    for item in bench["items"]:
        models = [
            m
            for m in bench["results"]
            if (a := _answer(bench, m, item["id"])) and a["valid"] and a["display_text"]
        ]
        if len(models) >= 2:
            options.append((item, models))
    if not options:
        raise HTTPException(404, NO_RESULTS)
    item, models = random.choice(options)
    a_model, b_model = random.sample(models, 2)
    facts = item["facts"]
    token = base64.urlsafe_b64encode(json.dumps([item["id"], a_model, b_model]).encode()).decode()
    return {
        "item_id": item["id"],
        "fen": item["fen"],
        "move_san": facts["player_move"]["san"],
        "classification": facts["classification"],
        "best_move_san": facts["best_move"]["san"] if facts.get("best_move") else None,
        "a": {"text": _answer(bench, a_model, item["id"])["display_text"]},
        "b": {"text": _answer(bench, b_model, item["id"])["display_text"]},
        "token": token,
    }


class Vote(BaseModel):
    token: str = Field(max_length=1000)
    winner: Literal["a", "b", "tie"]


@router.post("/vote")
def vote(body: Vote, request: Request, db: Db) -> dict:
    try:
        item_id, a_model, b_model = json.loads(base64.urlsafe_b64decode(body.token))
        bench = load_bench(request)
        if not all(_answer(bench, m, item_id) for m in (a_model, b_model)):
            raise ValueError(body.token)
    except (ValueError, binascii.Error):
        raise HTTPException(422, "Неверный токен пары") from None
    with db:
        db.execute(
            "INSERT INTO bench_votes (created_at, item_id, model_a, model_b, winner)"
            " VALUES (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), ?, ?, ?, ?)",
            (item_id, a_model, b_model, body.winner),
        )
    return {"votes": db.execute("SELECT COUNT(*) FROM bench_votes").fetchone()[0]}


@router.get("/results")
def results(request: Request, db: Db) -> dict:
    bench = load_bench(request)
    rows = db.execute("SELECT model_a, model_b, winner FROM bench_votes").fetchall()
    models = []
    for model, res in bench["results"].items():
        answers = res["answers"]
        wins = losses = ties = 0
        for r in rows:
            if model not in (r["model_a"], r["model_b"]):
                continue
            if r["winner"] == "tie":
                ties += 1
            elif (r["winner"] == "a") == (r["model_a"] == model):
                wins += 1
            else:
                losses += 1
        votes = wins + losses + ties
        models.append(
            {
                "model": model,
                "votes": votes,
                "wins": wins,
                "losses": losses,
                "ties": ties,
                "win_rate": wins / votes if votes else 0.0,
                "valid_pct": sum(a["valid"] for a in answers) / len(answers) if answers else 0.0,
                "mean_seconds": sum(a["seconds"] for a in answers) / len(answers)
                if answers
                else 0.0,
                "vram_gb": res.get("vram_gb"),
            }
        )
    models.sort(key=lambda m: (-m["win_rate"], -m["valid_pct"]))
    return {
        "models": models,
        "default_model": current_model(db, request.app.state.settings),
        "bench_created": bench["created"],
    }


class Default(BaseModel):
    model: str = Field(max_length=100)


@router.post("/default")
def set_default(body: Default, request: Request, db: Db) -> dict:
    if body.model not in load_bench(request)["results"]:
        raise HTTPException(422, "Такой модели нет в результатах сравнения")
    with db:
        db.execute(
            "INSERT INTO app_settings (key, value) VALUES ('llm_model', ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (body.model,),
        )
    return {"default_model": body.model}
