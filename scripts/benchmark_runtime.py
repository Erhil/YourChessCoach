"""Bounded real runtime measurement. Run explicitly on each machine; no speed extrapolation."""

import argparse
import json
import math
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from pathlib import Path

if __name__ == "__main__":
    from _common import use_project_python

    use_project_python()

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


class MeasuredLLM:
    """Observe typed failures before the lesson helper converts them to refusals."""

    def __init__(self, client):
        self.client = client
        self.failures = []

    def chat(self, system, user, model):
        try:
            return self.client.chat(system, user, model)
        except Exception as exc:
            cause = exc
            timeout = False
            while cause is not None:
                timeout |= isinstance(cause, (httpx.TimeoutException, TimeoutError))
                cause = cause.__cause__
            self.failures.append({"type": type(exc).__name__, "timeout": timeout})
            raise


def measure(job, trials, llm):
    samples = []
    for _ in range(trials):
        start = time.monotonic()
        before = len(llm.failures)
        try:
            result = job()
            sample = {"result": result, "error": result.get("reason")}
        except Exception as exc:  # noqa: BLE001 - measured failure is report data
            sample = {"error": str(exc), "exception_type": type(exc).__name__}
        sample.update(seconds=time.monotonic() - start, failures=llm.failures[before:])
        samples.append(sample)
    steady = sorted(x["seconds"] for x in samples[1:] if not x["error"])
    return {
        "first_call_s": samples[0]["seconds"],
        "errors": sum(bool(x["error"]) for x in samples),
        "timeouts": sum(any(f["timeout"] for f in x["failures"]) for x in samples),
        "sample_count": len(samples),
        "steady_success_count": len(steady),
        "steady_p50_s": statistics.median(steady) if steady else None,
        "steady_p95_s": steady[math.ceil(0.95 * len(steady)) - 1] if steady else None,
        "percentile_note": "Nearest rank, successful samples only; fewer than 20 steady successes is smoke evidence, not reliable tail latency.",
        "samples": samples,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--machine", choices=("development", "target"), required=True)
    parser.add_argument(
        "--trials",
        type=int,
        default=3,
        choices=range(2, 101),
        metavar="N",
        help="2–100 repetitions per workload (default: 3; smoke only)",
    )
    parser.add_argument("--model")
    parser.add_argument("--db", type=Path, help="Explicit isolated database (never production)")
    args = parser.parse_args()
    import chess
    from app.coach.explain import current_model
    from app.config import settings
    from app.db import connect
    from app.engines.pool import EnginePool
    from app.lessons.ask import answer_question, best_line, lesson_context, position_facts
    from app.lessons.loader import list_lessons
    from app.llm.client import OllamaClient
    from app.review.analysis import review_moves

    production_db = settings.app_db_path.resolve()
    if args.db:
        db_path = args.db.resolve()
        if db_path in {production_db, (ROOT / "data/app.db").resolve()}:
            parser.error("--db must not select the configured production database")
    else:
        scratch = ROOT / "docs/scratch"
        scratch.mkdir(parents=True, exist_ok=True)
        db_path = Path(tempfile.mkdtemp(prefix="runtime-", dir=scratch)) / "app.db"
    settings = replace(settings, app_db_path=db_path)
    with closing(connect(settings.app_db_path)) as db:
        model = args.model or current_model(db, settings)
    client = OllamaClient(settings.llm_base_url, settings.llm_timeout_s)
    llm = MeasuredLLM(client)
    pool = EnginePool(
        settings.engines_dir,
        settings.engine_pool_size,
        settings.stockfish_threads,
        settings.stockfish_hash,
    )
    board = chess.Board()
    # Fixed legal 40-ply game fragment, with development, castling and exchanges.
    game_san = "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5 Bb3 d6 c3 O-O h3 Nb8 d4 Nbd7 c4 c6 Nc3 Bb7 a3 Re8 Be3 Bf8 Rc1 h6 Qd2 exd4 Nxd4 Nc5 Ba2 Ncxe4 Nxe4 Nxe4 Qc2 Nf6"
    game = chess.Board()
    moves = []
    for san in game_san.split():
        moves.append(game.parse_san(san))
        game.push(moves[-1])
    lessons = list_lessons(settings.lessons_dir)
    lesson = next(item for item in lessons if item["slug"] == "board-and-moves")
    context = lesson_context(lesson)
    position = next(seg for seg in lesson["segments"] if seg["type"] == "chess")
    facts = position_facts(position["fen"], position["solution"], best_line(position["fen"], pool))
    question = "Как ходит конь?"
    report = {
        "machine": args.machine,
        "hardware": {
            "platform": platform.platform(),
            "cpu": platform.processor(),
            "logical_cpus": os.cpu_count(),
        },
        "model": model,
        "config": {
            "pool_size": settings.engine_pool_size,
            "threads": settings.stockfish_threads,
            "hash_mb": settings.stockfish_hash,
            "review_depth": settings.review_depth,
            "analysis_movetime_ms": settings.analysis_movetime_ms,
            "llm_timeout_s": settings.llm_timeout_s,
        },
        "first_call_is_cold": False,
        "note": "Existing model state is preserved. No target speed inference.",
        "inputs": {
            "database": str(db_path),
            "lesson_slug": lesson["slug"],
            "lesson_catalog_count": len(lessons),
            "question": question,
            "lesson_context_chars": len(context),
            "lesson_context_utf8_bytes": len(context.encode("utf-8")),
            "position_fen": position["fen"],
            "position_facts": facts,
            "game_san": game_san,
            "game_plies": len(moves),
            "overlap_scope": "40-ply review plus configured-time Stockfish analysis; engine-only, not opponent play",
        },
        "results": {},
    }
    if shutil.which("nvidia-smi"):
        report["gpu_before"] = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.used,memory.total", "--format=csv"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout

    def overlap():
        with ThreadPoolExecutor(max_workers=2) as ex:
            review = ex.submit(review_moves, pool, board, moves, settings)
            play = ex.submit(pool.analyse, game, None, settings.analysis_movetime_ms)
            return {"review_moves": len(review.result()), "play_depth": play.result()[0]}

    jobs = {
        "lesson_answer": lambda: answer_question(question, context, facts, llm, model),
        "stockfish": lambda: {
            "depth": pool.analyse(game, movetime_ms=settings.analysis_movetime_ms)[0]
        },
        "review_and_stockfish_analysis": overlap,
    }
    try:
        for name, job in jobs.items():
            report["results"][name] = measure(job, args.trials, llm)
    finally:
        pool.close()
        client._http.close()
    if shutil.which("nvidia-smi"):
        report["gpu_after"] = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.used,memory.total", "--format=csv"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"RUNTIME: {args.output}")


if __name__ == "__main__":
    main()
