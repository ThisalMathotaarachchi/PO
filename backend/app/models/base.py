"""Model provider abstraction. Agent code depends on this, not Ollama details."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ProviderError(Exception):
    def __init__(self, message: str, *, code: str = "model_error") -> None:
        super().__init__(message)
        self.code = code


class ModelRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ChatMessage(BaseModel):
    role: ModelRole
    content: str = ""
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


class ModelInfo(BaseModel):
    id: str
    name: str
    family: str = ""
    parameter_size: str = ""
    available: bool = True
    capabilities: list[str] = Field(default_factory=lambda: ["chat", "code"])
    context_length: int = 0
    digest: str = ""


class ModelResponse(BaseModel):
    content: str = ""
    model: str = ""
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    finish_reason: str = "stop"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    raw: dict[str, Any] = Field(default_factory=dict)


class ModelProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def health(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]:
        raise NotImplementedError

    @abstractmethod
    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.1,
        cancel_event: asyncio.Event | None = None,
    ) -> ModelResponse:
        raise NotImplementedError

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.1,
    ) -> AsyncIterator[str]:
        response = await self.chat(messages, model=model, tools=tools, temperature=temperature)
        if response.content:
            yield response.content
