"""Test Po agent repairs with real scenarios."""
import asyncio
import shutil
import tempfile
from pathlib import Path

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


async def setup_engine(workspace: Path) -> AgentEngine:
    """Setup a real agent engine."""
    db_dir = Path(tempfile.gettempdir()) / "po_repair_tests"
    db_dir.mkdir(exist_ok=True)
    test_db = db_dir / f"{workspace.name}.db"
    if test_db.exists():
        test_db.unlink()
    
    settings = Settings(
        database_path=str(test_db),
        agent_max_iterations=30,
        command_timeout_seconds=30.0,
    )
    
    db = Database(settings.resolve_database_path())
    await db.initialize()
    memory = MemoryManager(db)
    bus = EventBus()
    
    provider = OllamaProvider(host=settings.ollama_host, timeout=settings.ollama_timeout_seconds)
    
    sandbox = PathSandbox(workspace)
    policy = PermissionPolicy(sandbox, auto_approve_yellow=False)
    
    fs_tools = FilesystemTools(sandbox, bus, read_limit_bytes=settings.file_read_limit_bytes, ignore_directories=settings.ignore_directories)
    term = TerminalSession(sandbox, bus, default_timeout=settings.command_timeout_seconds, output_limit=settings.command_output_limit_bytes)
    search = SearchTools(sandbox, bus, max_results=settings.search_max_results, ignore_directories=set(settings.ignore_directories), max_file_bytes=settings.index_max_file_bytes)
    dev = DevelopmentTools(term, workspace, bus)
    git = GitTools(term)
    
    registry = ToolRegistry(filesystem=fs_tools, search=search, terminal=term, development=dev, git=git, policy=policy, bus=bus)
    model_registry = ModelRegistry(provider)
    router = ModelRouter(preferred=settings.preferred_model)
    index = ProjectIndex(memory=memory, ignore_directories=settings.ignore_directories, max_file_bytes=settings.index_max_file_bytes)
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
    
    return engine


async def test_simple_website():
    """Test A: Simple static website creation."""
    print("\n" + "="*80)
    print("TEST A: Simple Static Website")
    print("="*80)
    
    workspace = Path("D:/po_test_website")
    workspace.mkdir(exist_ok=True)
    
    # Clean workspace
    for item in workspace.iterdir():
        if item.is_file():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)
    
    engine = await setup_engine(workspace)
    
    task = Task(
        id="test-website-1",
        project_id="p-website",
        session_id="s-website",
        workspace_path=str(workspace),
        prompt="Create a simple personal portfolio website with HTML, CSS, and basic JavaScript. Include: index.html, styles.css, script.js, and a brief README."
    )
    
    print("Starting task...")
    result = await engine.run(task)
    
    print(f"\nStatus: {result.status}")
    print(f"Iterations: {result.iteration}")
    print(f"Summary: {result.summary}")
    
    # Verify
    assert result.status == TaskState.COMPLETED, f"Task failed: {result.error}"
    assert (workspace / "index.html").exists(), "index.html not created"
    assert (workspace / "styles.css").exists() or (workspace / "style.css").exists(), "CSS not created"
    assert (workspace / "README.md").exists(), "README not created"
    
    print("\n✓ TEST A PASSED")
    return result.iteration


async def test_windows_terminal():
    """Test B: Windows terminal shell commands."""
    print("\n" + "="*80)
    print("TEST B: Windows Terminal Commands")
    print("="*80)
    
    workspace = Path("D:/po_test_terminal")
    workspace.mkdir(exist_ok=True)
    
    for item in workspace.iterdir():
        if item.is_file():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)
    
    engine = await setup_engine(workspace)
    
    task = Task(
        id="test-terminal-1",
        project_id="p-terminal",
        session_id="s-terminal",
        workspace_path=str(workspace),
        prompt=(
            "Perform these operations:\n"
            "1. Create a file named test.txt with content 'Hello Po'\n"
            "2. List all files in the workspace\n"
            "3. Read test.txt content using a shell command"
        )
    )
    
    print("Starting task...")
    result = await engine.run(task)
    
    print(f"\nStatus: {result.status}")
    print(f"Iterations: {result.iteration}")
    print(f"Summary: {result.summary}")
    
    assert result.status == TaskState.COMPLETED, f"Task failed: {result.error}"
    assert (workspace / "test.txt").exists(), "test.txt not created"
    
    print("\n✓ TEST B PASSED")
    return result.iteration


async def test_existing_directory():
    """Test E: Create directory that already exists."""
    print("\n" + "="*80)
    print("TEST E: Idempotent Directory Creation")
    print("="*80)
    
    workspace = Path("D:/po_test_idempotent")
    workspace.mkdir(exist_ok=True)
    
    for item in workspace.iterdir():
        if item.is_file():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)
    
    # Pre-create a directory
    (workspace / "existing_dir").mkdir()
    
    engine = await setup_engine(workspace)
    
    task = Task(
        id="test-idempotent-1",
        project_id="p-idempotent",
        session_id="s-idempotent",
        workspace_path=str(workspace),
        prompt="Create a directory named 'existing_dir' and add a file named test.txt inside it."
    )
    
    print("Starting task...")
    result = await engine.run(task)
    
    print(f"\nStatus: {result.status}")
    print(f"Iterations: {result.iteration}")
    print(f"Summary: {result.summary}")
    
    assert result.status == TaskState.COMPLETED, f"Task failed: {result.error}"
    assert (workspace / "existing_dir" / "test.txt").exists(), "File not created in existing directory"
    
    print("\n✓ TEST E PASSED")
    return result.iteration


async def test_no_test_suite():
    """Test D: Project without tests."""
    print("\n" + "="*80)
    print("TEST D: Project Without Test Suite")
    print("="*80)
    
    workspace = Path("D:/po_test_notests")
    workspace.mkdir(exist_ok=True)
    
    for item in workspace.iterdir():
        if item.is_file():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)
    
    engine = await setup_engine(workspace)
    
    task = Task(
        id="test-notests-1",
        project_id="p-notests",
        session_id="s-notests",
        workspace_path=str(workspace),
        prompt="Create a simple landing page with HTML and CSS. No tests needed."
    )
    
    print("Starting task...")
    result = await engine.run(task)
    
    print(f"\nStatus: {result.status}")
    print(f"Iterations: {result.iteration}")
    print(f"Summary: {result.summary}")
    
    assert result.status == TaskState.COMPLETED, f"Task failed: {result.error}"
    assert (workspace / "index.html").exists() or any(workspace.glob("*.html")), "HTML not created"
    
    print("\n✓ TEST D PASSED")
    return result.iteration


async def main():
    """Run all tests."""
    print("\n" + "="*80)
    print("PO AGENT REPAIR TESTS")
    print("="*80)
    
    iterations = {}
    
    try:
        iterations['A'] = await test_simple_website()
    except Exception as e:
        print(f"\n✗ TEST A FAILED: {e}")
        iterations['A'] = None
    
    try:
        iterations['B'] = await test_windows_terminal()
    except Exception as e:
        print(f"\n✗ TEST B FAILED: {e}")
        iterations['B'] = None
    
    try:
        iterations['E'] = await test_existing_directory()
    except Exception as e:
        print(f"\n✗ TEST E FAILED: {e}")
        iterations['E'] = None
    
    try:
        iterations['D'] = await test_no_test_suite()
    except Exception as e:
        print(f"\n✗ TEST D FAILED: {e}")
        iterations['D'] = None
    
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    for test, iters in iterations.items():
        status = "PASS" if iters is not None else "FAIL"
        iter_str = f"({iters} iterations)" if iters else ""
        print(f"Test {test}: {status} {iter_str}")
    print("="*80 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
