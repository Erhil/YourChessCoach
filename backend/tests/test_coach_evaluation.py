"""The quality gate requires the actual answering passage, not a successful verdict."""

import importlib.util
import json
from pathlib import Path

import pytest

from app.coach.validator import to_display
from app.config import settings
from app.lessons import ask
from app.lessons.loader import list_lessons
from app.llm.client import LLMError

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("evaluate_coach", ROOT / "scripts/evaluate_coach.py")
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


def test_quality_gate_distinguishes_wrong_answers_and_unnecessary_refusals():
    case = {"answerable": True, "expected_passages": ["An answering paragraph."]}
    assert (
        evaluation.classify(case, {"answer": "An unrelated paragraph."}) == "wrong_accepted_answer"
    )
    assert (
        evaluation.classify(case, {"answer": None, "reason": ask.NO_ANSWER})
        == "unnecessary_refusal"
    )
    assert evaluation.classify(case, {"answer": case["expected_passages"][0]}) == "correct_answer"
    assert (
        evaluation.classify({**case, "answerable": False}, {"answer": "Text"})
        == "wrong_accepted_answer"
    )


def test_quality_gate_counts_only_semantic_refusals_as_correct():
    for answerable in (False, True):
        case = {"answerable": answerable, "expected_passages": []}
        for reason, expected in (
            (ask.UNAVAILABLE, "service_failure"),
            (ask.INEXACT, "format_failure"),
            (None, "format_failure"),
            ("Unknown refusal", "format_failure"),
            (ask.NO_ANSWER, "unnecessary_refusal" if answerable else "correct_refusal"),
        ):
            assert evaluation.classify(case, {"answer": None, "reason": reason}) == expected


def test_curated_expected_answers_remain_authored_passages():
    lessons = {x["slug"]: x for x in list_lessons(settings.lessons_dir)}
    cases = json.loads(
        (ROOT / "backend/tests/fixtures/lesson_questions.json").read_text(encoding="utf-8")
    )
    for case in cases:
        trusted = {
            to_display(p["text"])
            for p in ask.passage_catalog(ask.lesson_context(lessons[case["lesson"]]))
        }
        assert bool(case["expected_passages"]) == case["answerable"], case["id"]
        assert set(case["expected_passages"]) <= trusted, case["id"]


@pytest.mark.parametrize("failure", ["service_failure", "format_failure", "unnecessary_refusal"])
def test_quality_gate_exits_with_failure_and_records_all_results(tmp_path, monkeypatch, failure):
    cases = json.loads(
        (ROOT / "backend/tests/fixtures/lesson_questions.json").read_text(encoding="utf-8")
    )
    cases = [
        next(c for c in cases if c["answerable"]),
        next(c for c in cases if not c["answerable"]),
    ]
    fixture = tmp_path / "cases.json"
    fixture.write_text(json.dumps(cases), encoding="utf-8")
    output = tmp_path / "report.json"

    def chat(self, system, user, model):
        if failure == "service_failure":
            raise LLMError("offline")
        return "invalid JSON" if failure == "format_failure" else '{"passage":null}'

    monkeypatch.setattr(evaluation.OllamaClient, "chat", chat)
    monkeypatch.setattr(
        evaluation.sys,
        "argv",
        ["evaluate_coach.py", "--repeat", "1", "--fixture", str(fixture), "--output", str(output)],
    )
    assert evaluation.main() == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert sum(report["counts"].values()) == len(report["results"]) == 2
    assert report["counts"][failure] == (1 if failure == "unnecessary_refusal" else 2)
    assert report["counts"]["correct_refusal"] == (1 if failure == "unnecessary_refusal" else 0)
