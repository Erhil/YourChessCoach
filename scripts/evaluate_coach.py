"""Explicit real-Ollama regression run: python scripts/evaluate_coach.py --repeat 3.

No app server or user database is opened. The lesson HTTP route calls the same
answer_question function. Each question must match an authored answering passage.
"""

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

if __name__ == "__main__":
    from _common import use_project_python

    use_project_python()

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import settings
from app.lessons import ask
from app.lessons.loader import list_lessons
from app.llm.client import OllamaClient


def classify(case: dict, result: dict) -> str:
    answer = result.get("answer")
    if not answer:
        reason = result.get("reason")
        if reason == ask.UNAVAILABLE:
            return "service_failure"
        if reason != ask.NO_ANSWER:
            return "format_failure"
        return "unnecessary_refusal" if case["answerable"] else "correct_refusal"
    if not case["answerable"] or answer not in case["expected_passages"]:
        return "wrong_accepted_answer"
    return "correct_answer"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--model", default="qwen3.5:4b")
    parser.add_argument("--base-url", default=settings.llm_base_url)
    parser.add_argument("--timeout", type=float, default=settings.llm_timeout_s)
    parser.add_argument(
        "--fixture", type=Path, default=ROOT / "backend/tests/fixtures/lesson_questions.json"
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "data/lesson-quality/lesson-quality.json"
    )
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be positive")
    fixture = args.fixture.read_bytes()
    cases = json.loads(fixture)
    lessons = {x["slug"]: x for x in list_lessons(settings.lessons_dir)}
    http = OllamaClient(args.base_url, args.timeout)
    calls = []
    http._http.event_hooks["request"].append(
        lambda request: calls[-1].update(request=json.loads(request.content))
    )

    class RecordingClient:
        def chat(self, system, user, model):
            call = {"system": system, "user": user, "model": model}
            calls.append(call)
            start = time.perf_counter()
            try:
                call["response"] = http.chat(system, user, model)
                return call["response"]
            except Exception as exc:
                call["error"] = str(exc)
                raise
            finally:
                call["seconds"] = time.perf_counter() - start

    report = {
        "started_utc": datetime.now(UTC).isoformat(),
        "model": args.model,
        "base_url": args.base_url,
        "timeout_s": args.timeout,
        "repeat": args.repeat,
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, encoding="utf-8"
        ).strip(),
        "ask_source_sha256": hashlib.sha256(
            (ROOT / "backend/app/lessons/ask.py").read_bytes()
        ).hexdigest(),
        "fixture_sha256": hashlib.sha256(fixture).hexdigest(),
        "client_source_sha256": hashlib.sha256(
            (ROOT / "backend/app/llm/client.py").read_bytes()
        ).hexdigest(),
        "results": [],
    }
    try:
        for repeat in range(args.repeat):
            for case in cases:
                calls.clear()
                context = ask.lesson_context(lessons[case["lesson"]])
                start = time.perf_counter()
                # Position metadata is supplied as data, never as an answering passage.
                facts = None
                if "position" in case:
                    blocks = [
                        s for s in lessons[case["lesson"]]["segments"] if s["type"] == "chess"
                    ]
                    block = blocks[case["position"]]
                    facts = ask.position_facts(block["fen"], block["solution"], [])
                result = ask.answer_question(
                    case["question"], context, facts, RecordingClient(), args.model
                )
                status = classify(case, result)
                report["results"].append(
                    {
                        "case": case,
                        "repeat": repeat,
                        "result": result,
                        "status": status,
                        "seconds": time.perf_counter() - start,
                        "calls": list(calls),
                    }
                )
                print(f"{repeat + 1}: {case['id']}: {status}", flush=True)
    finally:
        report["counts"] = {
            key: sum(r["status"] == key for r in report["results"])
            for key in (
                "correct_answer",
                "correct_refusal",
                "unnecessary_refusal",
                "wrong_accepted_answer",
                "service_failure",
                "format_failure",
            )
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps(report["counts"]))
    return int(
        any(
            report["counts"][key]
            for key in (
                "unnecessary_refusal",
                "wrong_accepted_answer",
                "service_failure",
                "format_failure",
            )
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
