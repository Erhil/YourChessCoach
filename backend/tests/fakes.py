from app.llm.client import LLMError


class FakeLLM:
    """Test double: returns `text`, or raises LLMError when `text` is None."""

    def __init__(self, text: str | None = None):
        self.text = text
        self.calls: list[tuple[str, str, str]] = []

    def chat(self, system: str, user: str, model: str) -> str:
        self.calls.append((system, user, model))
        if self.text is None:
            raise LLMError("fake failure")
        return self.text
