"""Ollama chat client. A missing service is remembered for 30 s so a move never waits for it."""

import time
from ipaddress import ip_address
from typing import Protocol
from urllib.parse import urlsplit

import httpx

DOWN_FOR_S = 30.0


class LLMError(Exception):
    """The LLM gave no usable answer. The message is a short reason."""


class LLMClient(Protocol):
    def chat(self, system: str, user: str, model: str) -> str: ...


def use_environment_proxy(base_url: str) -> bool:
    """Keep remote proxy settings, but connect directly to the local Ollama service."""
    host = (urlsplit(base_url).hostname or "").rstrip(".").lower()
    if host == "localhost":
        return False
    try:
        return not ip_address(host).is_loopback
    except ValueError:
        return True


class OllamaClient:
    def __init__(
        self,
        base_url: str,
        timeout_s: float,
        transport: httpx.BaseTransport | None = None,
    ):
        self._url = base_url.rstrip("/") + "/api/chat"
        self._tags_url = base_url.rstrip("/") + "/api/tags"
        self._checked = (0.0, False)
        self._transport = transport
        self._trust_env = use_environment_proxy(base_url)
        self._http = httpx.Client(
            timeout=httpx.Timeout(timeout_s, connect=1.0),
            transport=transport,
            trust_env=self._trust_env,
        )
        self._down_until = 0.0

    def available(self) -> bool:
        """Cheap reachability check (GET /api/tags, 1 s), remembered for 30 s."""
        at, ok = self._checked
        if at and time.monotonic() - at < DOWN_FOR_S:
            return ok
        try:
            with httpx.Client(
                transport=self._transport, timeout=1.0, trust_env=self._trust_env
            ) as http:
                ok = http.get(self._tags_url).is_success
        except httpx.HTTPError:
            ok = False
        self._checked = (time.monotonic(), ok)
        return ok

    def readiness(self, model: str) -> dict:
        """Inspect installed models, without running or loading one."""
        try:
            response = self._http.get(self._tags_url, timeout=1.0)
            response.raise_for_status()
            names = {
                item.get("name", "") for item in response.json()["models"] if isinstance(item, dict)
            }
            present = model in names or (":" not in model and model + ":latest" in names)
            return {
                "reachable": True,
                "model_present": present,
                "available": present,
                "status": "ready" if present else "model_missing",
            }
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return {
                "reachable": False,
                "model_present": False,
                "available": False,
                "status": "unreachable",
            }

    def chat(self, system: str, user: str, model: str) -> str:
        if time.monotonic() < self._down_until:
            raise LLMError("ollama unavailable (recent connection failure)")
        payload = {
            "model": model,
            "stream": False,
            "think": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "options": {"temperature": 0.3, "num_predict": 220, "num_ctx": 4096},
        }
        try:
            resp = self._http.post(self._url, json=payload)
            resp.raise_for_status()
            content = (resp.json().get("message") or {}).get("content") or ""
        except httpx.ConnectError as e:
            self._down_until = time.monotonic() + DOWN_FOR_S
            raise LLMError(f"cannot connect: {type(e).__name__}") from e
        except httpx.ConnectTimeout as e:
            self._down_until = time.monotonic() + DOWN_FOR_S
            raise LLMError("connect timeout") from e
        except httpx.HTTPError as e:
            raise LLMError(f"request failed: {type(e).__name__}") from e
        except ValueError as e:
            raise LLMError("bad JSON in response") from e
        if not content.strip():
            raise LLMError("empty answer")
        return content.strip()
