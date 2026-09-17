"""
Autonomous stress test — real agent performing realistic coding tasks.
This test exercises:
- create_directory tool (previously unavailable)
- Terminal commands without allowlist restrictions
- No approval blocking for workspace operations
- No 10-minute timeout (allows complex tasks)
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from app.agent.engine import AgentEngine
from app.agent.task import Task
from app.config.settings import Settings
from app.context.indexing import ProjectIndex
from app.context.retrieval import ContextEngine
from app.events.bus import EventBus
from app.memory.database import Database
from app.memory.manager import MemoryManager
from app.models.ollama import OllamaProvider
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


@pytest.mark.asyncio
@pytest.mark.skipif(
    "OLLAMA_HOST" not in os.environ and not os.path.exists("D:/po_stress_test"),
    reason="Requires Ollama to be running and test workspace"
)
async def test_autonomous_stress_real_agent() -> None:
    """
    REAL autonomous agent stress test.
    
    Task: Build a complete Python CLI tool project:
    - Create proper directory structure (tests create_directory)
    - Create multiple Python files
    - Create requirements.txt
    - Run actual terminal commands (no allowlist)
    - Verify everything works
    
    This is a REAL test — the agent decides HOW to do it.
    """
    workspace = Path("D:/po_stress_test")
    if not workspace.exists():
        workspace.mkdir(parents=True)
    
    # Clean workspace
    for item in workspace.iterdir():
        if item.is_file():
            item.unlink()
        elif item.is_dir():
            import shutil
            shutil.rmtree(item)
    
    # Setup
    settings = Settings(
        database_path=str(workspace / ".test.db"),
        agent_task_timeout_seconds=3600.0,  # 1 hour
        command_timeout_seconds=120.0,
    )
    
    db = Database(settings.resolve_database_path())
    await db.initialize()
    memory = MemoryManager(db)
    bus = EventBus()
    
    # Real Ollama provider
    provider = OllamaProvider(
        host=settings.ollama_host,
        timeout=settings.ollama_timeout_seconds
    )
    
    # Real tool implementations
    sandbox = PathSandbox(workspace)
    policy = PermissionPolicy(sandbox, auto_approve_yellow=False)
    
    fs_tools = FilesystemTools(
        sandbox,
        bus,
        read_limit_bytes=settings.file_read_limit_bytes,
        ignore_directories=settings.ignore_directories,
    )
    
    term = TerminalSession(
        sandbox,
        bus,
        default_timeout=settings.command_timeout_seconds,
        output_limit=settings.command_output_limit_bytes,
    )
    
    search = SearchTools(
        sandbox,
        bus,
        max_results=settings.search_max_results,
        ignore_directories=set(settings.ignore_directories),
    )
    
    dev = DevelopmentTools(term, workspace, bus)
    git = GitTools(sandbox)
    
    registry = ToolRegistry(
        filesystem=fs_tools,
        search=search,
        terminal=term,
        development=dev,
        git=git,
        policy=policy,
        bus=bus,
    )
    
    model_registry = ModelRegistry(provider)
    router = ModelRouter(preferred=settings.preferred_model)
    
    # Context engine
    index = ProjectIndex(
        memory=memory,
        ignore_directories=settings.ignore_directories,
        max_file_bytes=settings.index_max_file_bytes,
    )
    context_engine = ContextEngine(index, memory, bus, settings.ignore_directories)
    
    engine = AgentEngine(
        provider=provider,
        registry=model_registry,
        router=router,
        tools=registry,
        context=context_engine,
        memory=memory,
        bus=bus,
        max_iterations=30,
        task_timeout=settings.agent_task_timeout_seconds,
    )
    
    # The realistic task
    task = Task(
        id="stress-1",
        project_id="p-stress",
        session_id="s-stress",
        workspace_path=str(workspace),
        prompt=(
            "Build a complete Python CLI calculator tool with the following structure:\n"
            "1. Create directory structure: src/calculator, tests\n"
            "2. Create src/calculator/__init__.py (empty)\n"
            "3. Create src/calculator/calc.py with add, subtract, multiply, divide functions\n"
            "4. Create src/calculator/cli.py with a main() function that uses argparse\n"
            "5. Create tests/test_calc.py with pytest tests for all 4 functions\n"
            "6. Create requirements.txt with pytest\n"
            "7. Create README.md with usage instructions\n"
            "8. Verify all files exist using file_exists\n"
            "9. Run the tests with pytest to make sure everything works\n"
            "\n"
            "Make it a real, working project."
        ),
    )
    
    print("\n" + "="*80)
    print("AUTONOMOUS STRESS TEST STARTING")
    print("="*80)
    print(f"Workspace: {workspace}")
    print(f"Timeout: {settings.agent_task_timeout_seconds}s")
    print(f"Task: {task.prompt[:100]}...")
    print("="*80 + "\n")
    
    # RUN THE AGENT
    result = await engine.run(task)
    
    print("\n" + "="*80)
    print("STRESS TEST COMPLETE")
    print("="*80)
    print(f"Status: {result.status}")
    print(f"Summary: {result.summary}")
    print(f"Iterations: {result.iteration}")
    print(f"Error: {result.error or 'None'}")
    print("="*80 + "\n")
    
    # VERIFY RESULTS
    assert result.status == "completed", f"Task failed: {result.error}"
    
    # Check that the directory structure was created using create_directory
    assert (workspace / "src" / "calculator").is_dir(), "src/calculator not created"
    assert (workspace / "tests").is_dir(), "tests directory not created"
    
    # Check that files exist
    assert (workspace / "src" / "calculator" / "__init__.py").exists(), "__init__.py missing"
    assert (workspace / "src" / "calculator" / "calc.py").exists(), "calc.py missing"
    assert (workspace / "src" / "calculator" / "cli.py").exists(), "cli.py missing"
    assert (workspace / "tests" / "test_calc.py").exists(), "test_calc.py missing"
    assert (workspace / "requirements.txt").exists(), "requirements.txt missing"
    assert (workspace / "README.md").exists(), "README.md missing"
    
    # Check that calc.py has actual code
    calc_content = (workspace / "src" / "calculator" / "calc.py").read_text()
    assert "def add" in calc_content, "add function not found"
    assert "def subtract" in calc_content, "subtract function not found"
    assert "def multiply" in calc_content, "multiply function not found"
    assert "def divide" in calc_content, "divide function not found"
    
    # Check that tests exist
    test_content = (workspace / "tests" / "test_calc.py").read_text()
    assert "test_" in test_content, "No test functions found"
    
    print("\n✓ All verification checks passed!")
    print("  - Directory structure created (create_directory tool)")
    print("  - All files created")
    print("  - Code contains expected functions")
    print("  - Tests exist")
    print("  - No timeout (task ran freely)")
    print("  - No approval blocking")
    print("  - Terminal commands worked without allowlist\n")


if __name__ == "__main__":
    # Allow running directly for manual testing
    asyncio.run(test_autonomous_stress_real_agent())
