"""End-to-end agent/tool flow against a deliberately broken project.

Uses MockModelProvider so the test is deterministic, but every filesystem and
test command is executed for real.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.engine import AgentEngine
from app.agent.state import TaskState
from app.agent.task import Task
from app.context.indexing import ProjectIndex
from app.context.retrieval import ContextEngine
from app.events.bus import EventBus
from app.memory.database import Database
from app.memory.manager import MemoryManager
from app.models.base import ChatMessage, ModelResponse
from app.models.mock import MockModelProvider
from app.models.registry import ModelRegistry
from app.models.router import ModelRouter
from app.permissions.policy import PermissionPolicy
from app.permissions.sandbox import PathSandbox
from app.tools.development import DevelopmentTools
from app.tools.filesystem import FilesystemTools
from app.tools.git import GitTools
from app.tools.registry import ToolRegistry
from app.tools.search import SearchTools
from app.tools.terminal import TerminalSession

BROKEN_SOURCE = "def add(a, b):\n    return a - b\n"
FIXED_SOURCE = "def add(a, b):\n    return a + b\n"
TEST_SOURCE = "from math_utils import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"


def _broken_project(root: Path) -> None:
    (root / "math_utils.py").write_text(BROKEN_SOURCE, encoding="utf-8")
    (root / "test_math_utils.py").write_text(TEST_SOURCE, encoding="utf-8")
    (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")


class FixProjectScript:
    """Scripted model that still drives real tools in order."""

    def __init__(self) -> None:
        self.step = 0

    def __call__(self, messages: list[ChatMessage]) -> ModelResponse:
        self.step += 1
        if self.step == 1:
            return ModelResponse(tool_calls=[{"tool": "list_directory", "arguments": {"path": "."}}])
        if self.step == 2:
            return ModelResponse(tool_calls=[{"tool": "read_file", "arguments": {"path": "math_utils.py"}}])
        if self.step == 3:
            return ModelResponse(tool_calls=[{"tool": "read_file", "arguments": {"path": "test_math_utils.py"}}])
        if self.step == 4:
            return ModelResponse(
                tool_calls=[{"tool": "write_file", "arguments": {"path": "math_utils.py", "content": FIXED_SOURCE}}]
            )
        if self.step == 5:
            return ModelResponse(tool_calls=[{"tool": "run_tests", "arguments": {}}])
        return ModelResponse(content='{"complete": true, "summary": "Done."}')


@pytest.mark.asyncio
async def test_fix_failing_tests_end_to_end(tmp_path: Path) -> None:
    workspace = tmp_path / "broken"
    workspace.mkdir()
    _broken_project(workspace)

    provider = MockModelProvider(handler=FixProjectScript())
    db = Database(tmp_path / "po.db")
    await db.initialize()
    memory = MemoryManager(db)
    await memory.upsert_project("p1", str(workspace), "broken")
    bus = EventBus()
    sandbox = PathSandbox(workspace)
    term = TerminalSession(sandbox, bus, default_timeout=40, output_limit=50_000)
    tools = ToolRegistry(
        filesystem=FilesystemTools(sandbox, bus),
        search=SearchTools(sandbox, bus, ignore_directories=[".git", "__pycache__"]),
        terminal=term,
        development=DevelopmentTools(term, workspace, bus),
        git=GitTools(term),
        policy=PermissionPolicy(sandbox),
        bus=bus,
    )
    engine = AgentEngine(
        provider=provider,
        registry=ModelRegistry(provider),
        router=ModelRouter(),
        tools=tools,
        context=ContextEngine(index=ProjectIndex(memory, [".git", "__pycache__"], 1_000_000), memory=memory, bus=bus, ignore_directories=[".git"]),
        memory=memory,
        bus=bus,
        max_iterations=15,
        task_timeout=90,
    )
    task = Task(
        prompt="Inspect this project, identify the failing problem, fix it, and run the tests.",
        project_id="p1",
        workspace_path=str(workspace),
    )
    done = await engine.run(task)
    assert done.status == TaskState.COMPLETED
    assert (workspace / "math_utils.py").read_text(encoding="utf-8") == FIXED_SOURCE
    recorded = await db.fetch_all("SELECT tool FROM tool_calls WHERE task_id = ?", (task.id,))
    tools_used = {row["tool"] for row in recorded}
    assert "list_directory" in tools_used or "read_file" in tools_used
    assert "write_file" in tools_used
    assert "run_tests" in tools_used
    events = [e.type for e in bus.recent(task_id=task.id)]
    assert "TASK_STARTED" in events
    assert "TASK_COMPLETED" in events
    # Tests were actually executed (not a fake summary)
    test_rows = await db.fetch_all(
        "SELECT tool, status FROM tool_calls WHERE task_id = ? AND tool = 'run_tests'",
        (task.id,),
    )
    assert test_rows
    assert any(row["status"] == "success" for row in test_rows)
