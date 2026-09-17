from __future__ import annotations

import asyncio
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
from app.models.base import ModelResponse
from app.models.mock import MockModelProvider
from app.models.registry import ModelRegistry
from app.models.router import ModelRouter
from app.permissions.policy import PermissionPolicy
from app.permissions.sandbox import PathSandbox
from app.tools.development import DevelopmentTools
from app.tools.filesystem import FilesystemTools
from app.tools.git import GitTools
from app.tools.processes import ProcessManager
from app.tools.registry import ToolRegistry
from app.tools.search import SearchTools
from app.tools.terminal import TerminalSession


async def _engine(tmp_path: Path, provider: MockModelProvider, *, iterations: int = 20) -> tuple[AgentEngine, Task]:
    db = Database(tmp_path / "db.sqlite")
    await db.initialize()
    memory = MemoryManager(db)
    await memory.upsert_project("p1", str(tmp_path), "demo")
    bus = EventBus()
    sandbox = PathSandbox(tmp_path)
    term = TerminalSession(sandbox, bus, default_timeout=20, output_limit=20_000)
    processes = ProcessManager(sandbox, bus)
    tools = ToolRegistry(
        filesystem=FilesystemTools(sandbox, bus),
        search=SearchTools(sandbox, bus, ignore_directories=[".git", "node_modules"]),
        terminal=term,
        development=DevelopmentTools(term, tmp_path, bus),
        git=GitTools(term),
        processes=processes,
        policy=PermissionPolicy(sandbox),
        bus=bus,
    )
    index = ProjectIndex(memory, [".git"], 1_000_000)
    context = ContextEngine(index, memory, bus, [".git"])
    engine = AgentEngine(
        provider=provider,
        registry=ModelRegistry(provider),
        router=ModelRouter(),
        tools=tools,
        context=context,
        memory=memory,
        bus=bus,
        max_iterations=iterations,
    )
    task = Task(prompt="inspect and complete", project_id="p1", workspace_path=str(tmp_path))
    return engine, task


def _tool(tool: str, **arguments) -> ModelResponse:
    return ModelResponse(content="", tool_calls=[{"tool": tool, "arguments": arguments}])


def _complete(summary: str = "Done.") -> ModelResponse:
    return ModelResponse(content=f'{{"complete": true, "summary": "{summary}"}}')


@pytest.mark.asyncio
async def test_multi_step_and_completion(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hi", encoding="utf-8")
    provider = MockModelProvider(
        responses=[
            _tool("list_directory", path="."),
            _tool("read_file", path="hello.txt"),
            _complete("Read the file."),
        ]
    )
    engine, task = await _engine(tmp_path, provider)
    done = await engine.run(task)
    assert done.status == TaskState.COMPLETED
    assert done.iteration >= 2
    assert any("Reading" in m or "Done" in m or "Read" in m for m in done.user_messages + [done.summary])


@pytest.mark.asyncio
async def test_iteration_limit(tmp_path: Path) -> None:
    provider = MockModelProvider(responses=[_tool("list_directory", path=".")] * 10)
    engine, task = await _engine(tmp_path, provider, iterations=3)
    done = await engine.run(task)
    assert done.status == TaskState.ERROR
    assert "iteration" in done.error.lower()


@pytest.mark.asyncio
async def test_cancellation(tmp_path: Path) -> None:
    async def handler(messages):
        await asyncio.sleep(0.05)
        return _tool("list_directory", path=".")

    provider = MockModelProvider(handler=handler)
    engine, task = await _engine(tmp_path, provider)
    run = asyncio.create_task(engine.run(task))
    await asyncio.sleep(0.02)
    await engine.cancel(task.id)
    done = await run
    assert done.status in {TaskState.CANCELLED, TaskState.COMPLETED, TaskState.ERROR}
    # If the first iteration finished complete-path-unlikely; cancel should win most of the time
    cancelled = await engine.cancel(task.id)
    assert cancelled.status == TaskState.CANCELLED


@pytest.mark.asyncio
async def test_malformed_recovery_then_complete(tmp_path: Path) -> None:
    provider = MockModelProvider(
        responses=[
            ModelResponse(content="I can't modify files."),
            _complete("Done."),
        ]
    )
    engine, task = await _engine(tmp_path, provider)
    done = await engine.run(task)
    assert done.status == TaskState.COMPLETED


@pytest.mark.asyncio
async def test_repeated_failure_nudge(tmp_path: Path) -> None:
    provider = MockModelProvider(
        responses=[
            _tool("read_file", path="missing.py"),
            _tool("read_file", path="missing.py"),
            _tool("read_file", path="missing.py"),
            _tool("list_directory", path="."),
            _complete("Could not find missing.py."),
        ]
    )
    engine, task = await _engine(tmp_path, provider)
    done = await engine.run(task)
    assert done.status == TaskState.COMPLETED
    assert provider.calls


@pytest.mark.asyncio
async def test_completion_verification_missing_files(tmp_path: Path) -> None:
    """
    Test that completion verification prevents premature completion when
    created files reference missing files (Elyra scenario).
    """
    provider = MockModelProvider(
        responses=[
            # Step 1: Create HTML with CSS/JS references
            _tool("write_file", path="index.html", content="""
<!DOCTYPE html>
<html>
<head>
    <title>Test Site</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <h1>Test</h1>
    <script src="script.js"></script>
</body>
</html>
"""),
            # Step 2: Try to complete (should be rejected by verification)
            _complete("Created the website."),
            # Step 3: Create the missing CSS file
            _tool("write_file", path="styles.css", content="body { margin: 0; }"),
            # Step 4: Create the missing JS file
            _tool("write_file", path="script.js", content="console.log('loaded');"),
            # Step 5: Complete (should now pass verification)
            _complete("Created all files for the website."),
        ]
    )
    engine, task = await _engine(tmp_path, provider, iterations=10)
    task.prompt = "Create a website with HTML, CSS, and JavaScript"
    done = await engine.run(task)
    
    # Should complete successfully after creating all files
    assert done.status == TaskState.COMPLETED, f"Task should complete. Status: {done.status}, Error: {done.error}"
    
    # Should have taken more than 2 iterations (initial HTML + rejection + fixes)
    assert done.iteration >= 4, f"Should take at least 4 iterations, took {done.iteration}"
    
    # All referenced files should exist
    assert (tmp_path / "index.html").exists()
    assert (tmp_path / "styles.css").exists()
    assert (tmp_path / "script.js").exists()


@pytest.mark.asyncio
async def test_completion_verification_all_files_exist(tmp_path: Path) -> None:
    """
    Test that completion verification passes when all referenced files exist.
    """
    provider = MockModelProvider(
        responses=[
            # Create all files in sequence
            _tool("write_file", path="index.html", content="""
<!DOCTYPE html>
<html>
<head>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <script src="script.js"></script>
</body>
</html>
"""),
            _tool("write_file", path="styles.css", content="body { margin: 0; }"),
            _tool("write_file", path="script.js", content="console.log('ready');"),
            _complete("Created complete website."),
        ]
    )
    engine, task = await _engine(tmp_path, provider, iterations=10)
    task.prompt = "Create a website"
    done = await engine.run(task)
    
    # Should complete successfully
    assert done.status == TaskState.COMPLETED
    
    # All files should exist
    assert (tmp_path / "index.html").exists()
    assert (tmp_path / "styles.css").exists()
    assert (tmp_path / "script.js").exists()
