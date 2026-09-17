from __future__ import annotations

import pytest

from app.agent.planner import AgentActionType, Planner
from app.models.base import ModelInfo, ModelResponse, ProviderError
from app.models.mock import MockModelProvider
from app.models.ollama import OllamaProvider, _normalize_tool_calls
from app.models.registry import ModelRegistry
from app.models.router import ModelRouter


@pytest.mark.asyncio
async def test_mock_provider_and_unavailable() -> None:
    provider = MockModelProvider(responses=[ModelResponse(content='{"complete": true, "summary": "ok"}')])
    models = await provider.list_models()
    assert models
    down = MockModelProvider(available=False)
    with pytest.raises(ProviderError) as exc:
        await down.list_models()
    assert exc.value.code == "ollama_unavailable"


@pytest.mark.asyncio
async def test_router_selects_installed_without_hardcoded_tag() -> None:
    models = [
        ModelInfo(id="some-other:latest", name="some-other:latest", family="llama", capabilities=["chat"]),
        ModelInfo(id="local-coder:latest", name="local-coder:latest", family="qwen", capabilities=["chat", "code"]),
    ]
    selected = ModelRouter().select(models, prompt="fix the failing tests")
    assert selected.id == "local-coder:latest"
    with pytest.raises(ProviderError):
        ModelRouter().select([])


def test_malformed_tool_output_parser() -> None:
    planner = Planner()
    bad = planner.parse(ModelResponse(content="I cannot modify files."))
    assert bad.type == AgentActionType.MALFORMED
    good = planner.parse(ModelResponse(content='{"tool": "read_file", "arguments": {"path": "a.py"}}'))
    assert good.type == AgentActionType.TOOL
    assert good.tool_call.tool == "read_file"
    fenced = planner.parse(ModelResponse(content='```json\n{"complete": true, "summary": "Done."}\n```'))
    assert fenced.type == AgentActionType.COMPLETE
    native = planner.parse(ModelResponse(content="", tool_calls=[{"tool": "list_directory", "arguments": {"path": "."}}]))
    assert native.tool_call.tool == "list_directory"


def test_normalize_ollama_tool_calls() -> None:
    raw = [{"function": {"name": "read_file", "arguments": '{"path": "x.py"}'}}]
    assert _normalize_tool_calls(raw)[0]["tool"] == "read_file"


@pytest.mark.asyncio
async def test_ollama_unavailable_host() -> None:
    provider = OllamaProvider("http://127.0.0.1:9", timeout=1)
    health = await provider.health()
    assert health["ok"] is False
    registry = ModelRegistry(provider)
    with pytest.raises(ProviderError):
        await registry.refresh()


@pytest.mark.asyncio
async def test_preferred_model_partial_match() -> None:
    models = [
        ModelInfo(id="alpha:1b", name="alpha:1b", family="other"),
        ModelInfo(id="qwen3:4b", name="qwen3:4b", family="qwen", capabilities=["code", "chat"]),
    ]
    selected = ModelRouter(preferred="qwen").select(models)
    assert "qwen" in selected.id
