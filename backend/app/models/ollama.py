"""Ollama local HTTP provider. Never downloads or stores model weights."""

from __future__ import annotations

import json
import re
import time
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urljoin
import asyncio

import httpx

from app.logging_setup import get_logger
from app.models.base import ChatMessage, ModelInfo, ModelProvider, ModelResponse, ModelRole, ProviderError

# Regex that matches <think>…</think> blocks emitted by thinking models when
# think:false is set but the model leaks partial traces anyway.  We strip these
# from the final content so the agent never sees chain-of-thought text.
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _strip_thinking(text: str) -> str:
    """Remove any <think>…</think> blocks from model output."""
    return _THINK_BLOCK.sub("", text).strip()


# Models whose family is known to support extended thinking via the
# Ollama-native `think` parameter.  We disable thinking for these models
# to keep responses concise and fast.
_THINKING_FAMILIES = frozenset({"qwen3", "deepseek-r1", "deepseek_r1", "qwq"})


def _is_thinking_model(model: str, family: str = "") -> bool:
    blob = f"{model} {family}".lower()
    return any(f in blob for f in _THINKING_FAMILIES)


class OllamaProvider(ModelProvider):
    name = "ollama"

    def __init__(self, host: str, timeout: float = 0.0, generation_timeout: float = 1800.0) -> None:
        self.host = host.rstrip("/")
        # `timeout` is an *idle* (between-chunk) timeout.  0 means wait as long
        # as the stream is alive — there is no overall generation deadline.
        self.timeout = timeout
        # `generation_timeout` is an overall wall-clock deadline for the entire
        # generation. 0 means no overall deadline.
        self.generation_timeout = generation_timeout
        self._log = get_logger("models.ollama")
        self._active_stream: httpx.Response | None = None

    def _url(self, path: str) -> str:
        return urljoin(self.host + "/", path.lstrip("/"))

    def _client_timeout(self) -> httpx.Timeout:
        """Connect fails fast; body reads have no overall deadline.

        If an idle timeout is configured (>0), it applies between streamed
        chunks only — a long generation that keeps producing tokens never
        expires because of wall-clock task time.
        """
        idle = self.timeout if self.timeout and self.timeout > 0 else None
        return httpx.Timeout(connect=5.0, read=idle, write=30.0, pool=5.0)

    async def health(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                response = await client.get(self._url("/api/tags"))
                response.raise_for_status()
                data = response.json()
                models = [m.get("name") for m in data.get("models", [])]
                return {"ok": True, "host": self.host, "models": models}
        except httpx.HTTPError as exc:
            return {"ok": False, "host": self.host, "error": str(exc)}

    async def list_models(self) -> list[ModelInfo]:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                response = await client.get(self._url("/api/tags"))
                response.raise_for_status()
                payload = response.json()
        except httpx.ConnectError as exc:
            raise ProviderError(
                f"Ollama is not reachable at {self.host}. Start Ollama locally and retry.",
                code="ollama_unavailable",
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Failed to list Ollama models: {exc}", code="ollama_error") from exc

        models: list[ModelInfo] = []
        for item in payload.get("models") or []:
            name = str(item.get("name") or item.get("model") or "")
            details = item.get("details") or {}
            family = str(details.get("family") or _family_from_name(name))
            size = str(details.get("parameter_size") or "")
            models.append(
                ModelInfo(
                    id=name,
                    name=name,
                    family=family,
                    parameter_size=size,
                    available=True,
                    capabilities=_capabilities(name, family),
                    digest=str(item.get("digest") or ""),
                )
            )
        return models

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.1,
        family: str = "",
        cancel_event: asyncio.Event | None = None,
    ) -> ModelResponse:
        """Send a chat request to Ollama.

        Always streams. Tool-call objects are collected from streamed chunks
        (including the final done chunk). Generation is not bounded by an
        overall wall-clock deadline; the caller may cancel via cancel_event.
        """
        suppress_think = _is_thinking_model(model, family)
        return await self._chat_streaming(
            messages,
            model=model,
            tools=tools,
            temperature=temperature,
            suppress_think=suppress_think,
            cancel_event=cancel_event,
        )

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _build_body(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        stream: bool,
        tools: list[dict[str, Any]] | None,
        temperature: float,
        suppress_think: bool,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "messages": [_to_ollama(m) for m in messages],
            "stream": stream,
            "options": {"temperature": temperature},
        }
        if tools:
            body["tools"] = tools
        if suppress_think:
            # Ollama native API top-level parameter — disables chain-of-thought
            # for qwen3 and other thinking models, keeping responses concise.
            body["think"] = False
        return body

    async def _chat_streaming(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        tools: list[dict[str, Any]] | None,
        temperature: float,
        suppress_think: bool,
        cancel_event: asyncio.Event | None = None,
    ) -> ModelResponse:
        """Stream tokens indefinitely until done, cancelled, or the connection dies."""
        body = self._build_body(
            messages,
            model=model,
            stream=True,
            tools=tools,
            temperature=temperature,
            suppress_think=suppress_think,
        )
        content_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        final_data: dict[str, Any] = {}
        # Track generation deadline if configured
        deadline = time.monotonic() + self.generation_timeout if self.generation_timeout and self.generation_timeout > 0 else None
        try:
            async with httpx.AsyncClient(timeout=self._client_timeout()) as client:
                async with client.stream("POST", self._url("/api/chat"), json=body) as response:
                    self._active_stream = response
                    if response.status_code == 404:
                        raise ProviderError(
                            f"Ollama model '{model}' is not installed. "
                            "Install it with Ollama or select an installed model.",
                            code="model_unavailable",
                        )
                    response.raise_for_status()
                    async for line in _lines_until_cancel(response, cancel_event):
                        # Check generation deadline
                        if deadline is not None and time.monotonic() > deadline:
                            raise ProviderError(
                                "Model generation exceeded wall-clock timeout",
                                code="generation_timeout",
                            )
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        message = chunk.get("message") or {}
                        piece = message.get("content") or ""
                        if piece:
                            content_parts.append(piece)
                        chunk_calls = _normalize_tool_calls(message.get("tool_calls") or [])
                        if chunk_calls:
                            tool_calls = chunk_calls
                        if chunk.get("done"):
                            final_data = chunk
                            more = _normalize_tool_calls((chunk.get("message") or {}).get("tool_calls") or [])
                            if more:
                                tool_calls = more
        except ProviderError:
            raise
        except httpx.ConnectError as exc:
            raise ProviderError(f"Ollama is not reachable at {self.host}", code="ollama_unavailable") from exc
        except httpx.TimeoutException as exc:
            raise ProviderError(
                "Ollama stopped producing output (idle connection). "
                "The model may be unresponsive; retry or cancel the task.",
                code="timeout",
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Ollama chat failed: {exc}", code="ollama_error") from exc
        finally:
            self._active_stream = None

        content = _strip_thinking("".join(content_parts))
        usage = final_data.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_eval_count") or final_data.get("prompt_eval_count") or 0)
        completion_tokens = int(usage.get("eval_count") or final_data.get("eval_count") or 0)
        self._log.info(
            "ollama stream complete",
            extra={"extra_data": {
                "model": model,
                "chars": len(content),
                "tool_calls": len(tool_calls),
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            }},
        )
        return ModelResponse(
            content=content,
            model=final_data.get("model") or model,
            tool_calls=tool_calls,
            finish_reason=str(final_data.get("done_reason") or "stop"),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            raw=final_data,
        )

    async def _chat_blocking(self, *args: Any, **kwargs: Any) -> ModelResponse:
        """Compatibility wrapper: blocking chat is streaming under the hood."""
        return await self._chat_streaming(*args, **kwargs)

    def _parse_response(self, data: dict[str, Any], model: str) -> ModelResponse:
        message = data.get("message") or {}
        content = str(message.get("content") or "")
        content = _strip_thinking(content)
        tool_calls = _normalize_tool_calls(message.get("tool_calls") or [])
        usage = data.get("usage") or {}
        self._log.info(
            "ollama chat",
            extra={"extra_data": {
                "model": model,
                "tool_calls": len(tool_calls),
                "chars": len(content),
            }},
        )
        return ModelResponse(
            content=content,
            model=data.get("model") or model,
            tool_calls=tool_calls,
            finish_reason=str(data.get("done_reason") or "stop"),
            prompt_tokens=int(usage.get("prompt_eval_count") or data.get("prompt_eval_count") or 0),
            completion_tokens=int(usage.get("eval_count") or data.get("eval_count") or 0),
            raw=data,
        )

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.1,
    ) -> AsyncIterator[str]:
        body: dict[str, Any] = {
            "model": model,
            "messages": [_to_ollama(m) for m in messages],
            "stream": True,
            "options": {"temperature": temperature},
        }
        if tools:
            body["tools"] = tools
        if _is_thinking_model(model):
            body["think"] = False
        try:
            async with httpx.AsyncClient(timeout=self._client_timeout()) as client:
                async with client.stream("POST", self._url("/api/chat"), json=body) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        piece = ((chunk.get("message") or {}).get("content")) or ""
                        if piece:
                            yield piece
        except httpx.ConnectError as exc:
            raise ProviderError(f"Ollama is not reachable at {self.host}", code="ollama_unavailable") from exc


def _to_ollama(message: ChatMessage) -> dict[str, Any]:
    payload: dict[str, Any] = {"role": message.role.value, "content": message.content}
    if message.role == ModelRole.TOOL and message.name:
        payload["role"] = "tool"
        payload["name"] = message.name
    if message.tool_calls:
        # Convert from our internal {"tool": name, "arguments": {...}} format back to
        # Ollama's expected {"function": {"name": ..., "arguments": {...}}} format.
        payload["tool_calls"] = [
            {
                "function": {
                    "name": tc.get("tool") or tc.get("name") or "",
                    "arguments": tc.get("arguments") or tc.get("function", {}).get("arguments") or {},
                }
            }
            for tc in message.tool_calls
        ]
    return payload


def _normalize_tool_calls(raw: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        fn = item.get("function") or item
        name = fn.get("name") or item.get("name")
        args = fn.get("arguments") or item.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {"_raw": args}
        if name:
            normalized.append({"tool": name, "arguments": args if isinstance(args, dict) else {}})
    return normalized


def _family_from_name(name: str) -> str:
    lower = name.lower()
    for family in ("qwen3", "qwen", "llama", "mistral", "gemma", "phi", "deepseek", "codellama", "starcoder"):
        if family in lower:
            return family
    return "unknown"


def _capabilities(name: str, family: str) -> list[str]:
    caps = ["chat"]
    blob = f"{name} {family}".lower()
    if any(token in blob for token in ("code", "coder", "starcoder", "deepseek", "qwen")):
        caps.append("code")
    caps.append("tools")
    return caps
