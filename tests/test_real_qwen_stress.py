"""
REAL Qwen3-Coder 30B stress tests.

These tests use the ACTUAL:
- Po Agent Engine
- Ollama
- qwen3-coder:30b
- real ToolRegistry
- real filesystem
- real terminal

NO mocked model. NO fake tool calls. NO pre-created files.

The agent must autonomously complete realistic coding tasks.
"""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from app.agent.engine import AgentEngine
from app.agent.state import TaskState
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


async def _setup_real_engine(workspace: Path) -> tuple[AgentEngine, Settings]:
    """Create a fully functional agent with real Ollama provider."""
    # Put database OUTSIDE the disposable workspace to avoid lock conflicts
    import tempfile
    db_dir = Path(tempfile.gettempdir()) / "po_test_dbs"
    db_dir.mkdir(exist_ok=True)
    test_db_path = db_dir / f"{workspace.name}.db"
    
    settings = Settings(
        database_path=str(test_db_path),
        agent_task_timeout_seconds=3600.0,
        agent_max_iterations=50,
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
        max_file_bytes=settings.index_max_file_bytes,
    )
    
    dev = DevelopmentTools(term, workspace, bus)
    git = GitTools(term)
    
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
        max_iterations=settings.agent_max_iterations,
        task_timeout=settings.agent_task_timeout_seconds,
    )
    
    return engine, settings


@pytest.mark.asyncio
@pytest.mark.skipif(
    not Path("D:/po_stress_test").exists(),
    reason="Stress test workspace not found - create D:/po_stress_test manually"
)
async def test_qwen_python_calculator() -> None:
    """
    REAL Qwen3-Coder 30B test: Build a Python CLI calculator.
    
    The agent must:
    - Create directory structure
    - Write Python source files
    - Create tests
    - Run pytest
    - Fix any failures
    - Verify the result
    """
    workspace = Path("D:/po_stress_test")
    
    # Clean workspace (database is now external)
    for item in workspace.iterdir():
        if item.is_file():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)
    
    engine, settings = await _setup_real_engine(workspace)
    
    task = Task(
        id="qwen-calc-1",
        project_id="p-qwen-calc",
        session_id="s-qwen-calc",
        workspace_path=str(workspace),
        prompt=(
            "Build a complete Python CLI calculator application.\n\n"
            "Requirements:\n"
            "1. Create directory structure: src/calculator, tests\n"
            "2. Create src/calculator/__init__.py (empty)\n"
            "3. Create src/calculator/calc.py with functions: add, subtract, multiply, divide\n"
            "4. Create src/calculator/cli.py with a main() function using argparse\n"
            "5. Create tests/test_calc.py with pytest tests for all 4 functions\n"
            "6. Create requirements.txt with pytest\n"
            "7. Create README.md with usage instructions\n"
            "8. Run the tests with pytest\n"
            "9. If tests fail, fix the code and run tests again\n"
            "10. Verify all files exist using file_exists\n"
            "11. Report what was created\n\n"
            "This must be a real, working calculator."
        ),
    )
    
    print("\n" + "="*80)
    print("QWEN PYTHON CALCULATOR TEST STARTING")
    print("="*80)
    print(f"Workspace: {workspace}")
    print(f"Max iterations: {settings.agent_max_iterations}")
    print(f"Timeout: {settings.agent_task_timeout_seconds}s")
    print("="*80 + "\n")
    
    result = await engine.run(task)
    
    print("\n" + "="*80)
    print("TEST COMPLETE")
    print("="*80)
    print(f"Status: {result.status}")
    print(f"Iterations: {result.iteration}/{settings.agent_max_iterations}")
    print(f"Summary: {result.summary}")
    print(f"Error: {result.error or 'None'}")
    print("="*80 + "\n")
    
    # Verify results
    assert result.status == TaskState.COMPLETED, f"Task failed: {result.error}"
    assert (workspace / "src" / "calculator").is_dir(), "src/calculator not created"
    assert (workspace / "tests").is_dir(), "tests directory not created"
    assert (workspace / "src" / "calculator" / "calc.py").exists(), "calc.py missing"
    assert (workspace / "tests" / "test_calc.py").exists(), "test_calc.py missing"
    
    calc_content = (workspace / "src" / "calculator" / "calc.py").read_text()
    assert "def add" in calc_content, "add function missing"
    assert "def subtract" in calc_content, "subtract function missing"
    assert "def multiply" in calc_content, "multiply function missing"
    assert "def divide" in calc_content, "divide function missing"
    
    print("\n✓ QWEN PYTHON CALCULATOR TEST PASSED")


@pytest.mark.asyncio
@pytest.mark.skipif(
    not Path("D:/po_stress_test_2").exists(),
    reason="Stress test workspace 2 not found - create D:/po_stress_test_2 manually"
)
async def test_qwen_ai_agent_app() -> None:
    """
    REAL Qwen3-Coder 30B test: Build a small AI agent application.
    
    The agent must:
    - Create project structure
    - Write Python source files for an AI agent
    - Handle model provider abstraction
    - Create CLI interface
    - Create configuration
    - Write README
    - Verify the result
    """
    workspace = Path("D:/po_stress_test_2")
    
    # Clean workspace (no need to skip .test.db - it's now external)
    for item in workspace.iterdir():
        if item.is_file():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)
    
    engine, settings = await _setup_real_engine(workspace)
    
    task = Task(
        id="qwen-agent-1",
        project_id="p-qwen-agent",
        session_id="s-qwen-agent",
        workspace_path=str(workspace),
        prompt=(
            "Create a small AI agent application in Python.\n\n"
            "Requirements:\n"
            "1. Create directory structure: src/agent, config\n"
            "2. Create src/agent/__init__.py\n"
            "3. Create src/agent/provider.py with a ModelProvider base class\n"
            "4. Create src/agent/cli.py with a main() function that accepts user prompts\n"
            "5. Create config/default.yaml with model configuration\n"
            "6. Create requirements.txt with necessary dependencies\n"
            "7. Create README.md explaining how to use the agent\n"
            "8. Verify all files exist using file_exists\n"
            "9. Report what was created\n\n"
            "The agent should have a simple architecture with provider abstraction."
        ),
    )
    
    print("\n" + "="*80)
    print("QWEN AI AGENT APP TEST STARTING")
    print("="*80)
    print(f"Workspace: {workspace}")
    print(f"Max iterations: {settings.agent_max_iterations}")
    print("="*80 + "\n")
    
    result = await engine.run(task)
    
    print("\n" + "="*80)
    print("TEST COMPLETE")
    print("="*80)
    print(f"Status: {result.status}")
    print(f"Iterations: {result.iteration}/{settings.agent_max_iterations}")
    print(f"Summary: {result.summary}")
    print("="*80 + "\n")
    
    # Verify results
    assert result.status == TaskState.COMPLETED, f"Task failed: {result.error}"
    assert (workspace / "src" / "agent").is_dir(), "src/agent not created"
    assert (workspace / "src" / "agent" / "provider.py").exists(), "provider.py missing"
    assert (workspace / "src" / "agent" / "cli.py").exists(), "cli.py missing"
    assert (workspace / "README.md").exists(), "README.md missing"
    
    print("\n✓ QWEN AI AGENT APP TEST PASSED")


@pytest.mark.asyncio
@pytest.mark.skipif(
    not Path("D:/po_stress_test_3").exists(),
    reason="Stress test workspace 3 not found - create D:/po_stress_test_3 manually"
)
async def test_qwen_destructive_cleanup() -> None:
    """
    REAL Qwen3-Coder 30B test: Delete all workspace contents.
    
    Tests that Po can:
    - Use delete_directory and delete_file tools
    - Iterate through workspace contents
    - Verify deletion with file_exists
    - Handle the user's explicit destructive request
    """
    workspace = Path("D:/po_stress_test_3")
    
    # Create test content
    (workspace / "dir1").mkdir(exist_ok=True)
    (workspace / "dir1" / "file1.txt").write_text("test1")
    (workspace / "dir2").mkdir(exist_ok=True)
    (workspace / "dir2" / "subdir").mkdir(exist_ok=True)
    (workspace / "dir2" / "subdir" / "file2.txt").write_text("test2")
    (workspace / "file3.txt").write_text("test3")
    (workspace / "file4.py").write_text("print('test')")
    
    engine, settings = await _setup_real_engine(workspace)
    
    task = Task(
        id="qwen-delete-1",
        project_id="p-qwen-delete",
        session_id="s-qwen-delete",
        workspace_path=str(workspace),
        prompt=(
            "Delete everything inside this workspace.\n\n"
            "Requirements:\n"
            "1. List all files and directories in the workspace\n"
            "2. Delete ALL directories recursively using delete_directory\n"
            "3. Delete ALL files using delete_file\n"
            "4. Do NOT delete the workspace directory itself (only its contents)\n"
            "5. Verify the workspace is empty using list_directory\n"
            "6. Report what was deleted\n\n"
            "The workspace must be completely empty when done."
        ),
    )
    
    print("\n" + "="*80)
    print("QWEN DESTRUCTIVE CLEANUP TEST STARTING")
    print("="*80)
    print(f"Workspace: {workspace}")
    print("="*80 + "\n")
    
    result = await engine.run(task)
    
    print("\n" + "="*80)
    print("TEST COMPLETE")
    print("="*80)
    print(f"Status: {result.status}")
    print(f"Summary: {result.summary}")
    print("="*80 + "\n")
    
    # Verify results
    assert result.status == TaskState.COMPLETED, f"Task failed: {result.error}"
    assert workspace.exists(), "Workspace directory was deleted (should only delete contents)"
    
    # Check workspace is empty (database is now external)
    contents = list(workspace.iterdir())
    assert len(contents) == 0, f"Workspace not empty: {[str(item) for item in contents]}"
    
    print("\n✓ QWEN DESTRUCTIVE CLEANUP TEST PASSED")


if __name__ == "__main__":
    # Allow running directly
    import sys
    if len(sys.argv) > 1:
        test_name = sys.argv[1]
        if test_name == "calc":
            asyncio.run(test_qwen_python_calculator())
        elif test_name == "agent":
            asyncio.run(test_qwen_ai_agent_app())
        elif test_name == "delete":
            asyncio.run(test_qwen_destructive_cleanup())
        else:
            print("Usage: python test_real_qwen_stress.py [calc|agent|delete]")
    else:
        print("Usage: python test_real_qwen_stress.py [calc|agent|delete]")
