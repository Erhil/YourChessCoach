import json

import httpx
import pytest

from app.llm import client as client_mod
from app.llm.client import LLMError, OllamaClient


def make(handler) -> OllamaClient:
    return OllamaClient("http://ollama.test", 5, transport=httpx.MockTransport(handler))


def test_ollama_request_and_answer():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content), path=request.url.path)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": " Ответ "}})

    assert make(handler).chat("sys", "usr", "qwen3.5:4b") == "Ответ"
    assert seen["path"] == "/api/chat"
    assert seen["stream"] is False
    assert seen["think"] is False
    assert seen["model"] == "qwen3.5:4b"
    assert seen["options"]["num_predict"] == 220
    assert [m["role"] for m in seen["messages"]] == ["system", "user"]


@pytest.mark.parametrize("body", [{"message": {"content": ""}}, {"message": {"content": "  "}}, {}])
def test_empty_content_is_error(body):
    with pytest.raises(LLMError, match="empty"):
        make(lambda r: httpx.Response(200, json=body)).chat("s", "u", "m")


def test_http_error_is_llm_error():
    with pytest.raises(LLMError):
        make(lambda r: httpx.Response(500, text="boom")).chat("s", "u", "m")


def test_connection_error_marks_unavailable_for_30s(monkeypatch):
    calls = []
    now = [1000.0]
    monkeypatch.setattr(client_mod.time, "monotonic", lambda: now[0])

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("refused")
        return httpx.Response(200, json={"message": {"content": "ok"}})

    c = make(handler)
    with pytest.raises(LLMError, match="connect"):
        c.chat("s", "u", "m")
    now[0] += 29
    with pytest.raises(LLMError, match="unavailable"):
        c.chat("s", "u", "m")
    assert len(calls) == 1  # no request during the pause
    now[0] += 2
    assert c.chat("s", "u", "m") == "ok"
    assert len(calls) == 2
