"""Deterministic model provider for tests. Does not replace OllamaProvider."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.models.base import ChatMessage, ModelInfo, ModelProvider, ModelResponse, ProviderError

ResponseFactory = Callable[[list[ChatMessage]], ModelResponse | Awaitable[ModelResponse]]


class MockModelProvider(ModelProvider):
    name = "mock"

    def __init__(
        self,
        *,
        responses: list[ModelResponse] | None = None,
        handler: ResponseFactory | None = None,
        models: list[ModelInfo] | None = None,
        available: bool = True,
    ) -> None:
        self._responses = list(responses or [])
        self._handler = handler
        self._index = 0
        self._available = available
        self.models = models or [
            ModelInfo(id="mock-coder", name="mock-coder", family="mock", capabilities=["chat", "code", "tools"])
        ]
        self.calls: list[list[ChatMessage]] = []

    async def health(self) -> dict[str, Any]:
        return {"ok": self._available, "host": "mock", "models": [m.id for m in self.models]}

    async def list_models(self) -> list[ModelInfo]:
        if not self._available:
            raise ProviderError("Mock Ollama unavailable", code="ollama_unavailable")
        return list(self.models)

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.1,
        family: str = "",
    ) -> ModelResponse:
        if not self._available:
            raise ProviderError("Mock Ollama unavailable", code="ollama_unavailable")
        self.calls.append(messages)
        if self._handler:
            result = self._handler(messages)
            if hasattr(result, "__await__"):
                result = await result  # type: ignore[assignment]
            assert isinstance(result, ModelResponse)
            result.model = result.model or model
            return result
        if self._index >= len(self._responses):
            return ModelResponse(
                content='{"complete": true, "summary": "Done."}',
                model=model,
            )
        response = self._responses[self._index]
        self._index += 1
        response.model = response.model or model
        return response
