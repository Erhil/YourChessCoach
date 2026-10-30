"""Runtime measurement observes the real HTTP-to-lesson failure boundary."""

import importlib.util
from pathlib import Path

import httpx
import pytest

from app.lessons.ask import answer_question
from app.llm.client import OllamaClient

spec = importlib.util.spec_from_file_location(
    "benchmark_runtime", Path(__file__).resolve().parents[2] / "scripts/benchmark_runtime.py"
)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


@pytest.mark.parametrize(
    "error_type,expected_timeouts", [(httpx.ReadTimeout, 2), (httpx.ConnectError, 0)]
)
def test_runtime_counts_typed_errors_before_lesson_fallback(error_type, expected_timeouts):
    def fail(request):
        raise error_type("network failure", request=request)

    client = OllamaClient("http://localhost", 1, transport=httpx.MockTransport(fail))
    measured = runtime.MeasuredLLM(client)
    try:
        report = runtime.measure(
            lambda: answer_question("question", "authored text", None, measured, "test"),
            2,
            measured,
        )
    finally:
        client._http.close()
    assert report["errors"] == 2
    assert report["timeouts"] == expected_timeouts
    assert report["steady_success_count"] == 0
    assert report["steady_p95_s"] is None
