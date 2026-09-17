"""Final acceptance tests for Po autonomous agent repairs.

These tests verify Po works correctly with REAL qwen3-coder:30b.
"""
import asyncio
import shutil
import tempfile
import time
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
from app.tools.processes import ProcessManager
from app.tools.registry import ToolRegistry
from app.tools.search import SearchTools
from app.tools.terminal import TerminalSession


async def setup_engine(workspace: Path) -> AgentEngine:
    """Setup real agent with Ollama."""
    db_dir = Path(tempfile.gettempdir()) / "po_final_tests"
    db_dir.mkdir(exist_ok=True)
    test_db = db_dir / f"{workspace.name}.db"
    if test_db.exists():
        test_db.unlink()
    
    settings = Settings(database_path=str(test_db), agent_max_iterations=40)
    
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
    processes = ProcessManager(sandbox, bus)
    
    registry = ToolRegistry(filesystem=fs_tools, search=search, terminal=term, development=dev, git=git, processes=processes, policy=policy, bus=bus)
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
    )
    
    return engine


async def test_1_clothing_website():
    """TEST 1: Create Elyra clothing brand website."""
    print("\n" + "="*80)
    print("TEST 1: ELYRA CLOTHING WEBSITE")
    print("="*80)
    
    workspace = Path("D:/po_final_test_elyra")
    workspace.mkdir(exist_ok=True)
    
    for item in workspace.iterdir():
        if item.is_file():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)
    
    engine = await setup_engine(workspace)
    
    task = Task(
        id="test-elyra-1",
        project_id="p-elyra",
        session_id="s-elyra",
        workspace_path=str(workspace),
        prompt="Create a simple premium clothing website for a fictional brand called Elyra. Include a homepage, product section, responsive styling, and a coherent brand identity. Use HTML, CSS, and minimal JavaScript."
    )
    
    print("\nStarting task...")
    start = time.time()
    result = await engine.run(task)
    duration = time.time() - start
    
    print(f"\nStatus: {result.status}")
    print(f"Iterations: {result.iteration}")
    print(f"Duration: {duration:.1f}s")
    print(f"Summary: {result.summary}")
    
    # Verify
    assert result.status == TaskState.COMPLETED, f"Task failed: {result.error}"
    
    html_files = list(workspace.glob("*.html")) or list(workspace.glob("**/*.html"))
    assert len(html_files) > 0, "No HTML files created"
    
    # Check semantic correctness - should mention clothing/fashion, NOT data science
    readme = workspace / "README.md"
    if readme.exists():
        content = readme.read_text().lower()
        assert "clothing" in content or "fashion" in content or "elyra" in content, "README doesn't describe clothing brand"
        assert "data science" not in content and "ai-powered" not in content, "README contains unrelated concepts!"
    
    print(f"\n✓ TEST 1 PASSED - {result.iteration} iterations, {duration:.1f}s")
    return {"test": 1, "iterations": result.iteration, "duration": duration, "status": "PASS"}


async def test_2_windows_shell():
    """TEST 2: Windows shell commands."""
    print("\n" + "="*80)
    print("TEST 2: WINDOWS SHELL COMMANDS")
    print("="*80)
    
    workspace = Path("D:/po_final_test_shell")
    workspace.mkdir(exist_ok=True)
    
    for item in workspace.iterdir():
        if item.is_file():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)
    
    engine = await setup_engine(workspace)
    
    task = Task(
        id="test-shell-1",
        project_id="p-shell",
        session_id="s-shell",
        workspace_path=str(workspace),
        prompt="Create a directory named 'testdir', create a file 'test.txt' inside it with content 'Hello Po', then use shell commands to list the directory contents and verify the file exists."
    )
    
    print("\nStarting task...")
    start = time.time()
    result = await engine.run(task)
    duration = time.time() - start
    
    print(f"\nStatus: {result.status}")
    print(f"Iterations: {result.iteration}")
    print(f"Duration: {duration:.1f}s")
    
    assert result.status == TaskState.COMPLETED, f"Task failed: {result.error}"
    assert (workspace / "testdir" / "test.txt").exists(), "File not created"
    
    print(f"\n✓ TEST 2 PASSED - {result.iteration} iterations, {duration:.1f}s")
    return {"test": 2, "iterations": result.iteration, "duration": duration, "status": "PASS"}


async def test_3_background_server():
    """TEST 3: Long-running background server."""
    print("\n" + "="*80)
    print("TEST 3: BACKGROUND SERVER")
    print("="*80)
    
    workspace = Path("D:/po_final_test_server")
    workspace.mkdir(exist_ok=True)
    
    for item in workspace.iterdir():
        if item.is_file():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)
    
    engine = await setup_engine(workspace)
    
    task = Task(
        id="test-server-1",
        project_id="p-server",
        session_id="s-server",
        workspace_path=str(workspace),
        prompt="Create a simple HTML file index.html, then start a Python HTTP server on port 8765 using start_process. Check the server status, then stop it."
    )
    
    print("\nStarting task...")
    start = time.time()
    result = await engine.run(task)
    duration = time.time() - start
    
    print(f"\nStatus: {result.status}")
    print(f"Iterations: {result.iteration}")
    print(f"Duration: {duration:.1f}s")
    
    assert result.status == TaskState.COMPLETED, f"Task failed: {result.error}"
    assert (workspace / "index.html").exists(), "HTML file not created"
    
    print(f"\n✓ TEST 3 PASSED - {result.iteration} iterations, {duration:.1f}s")
    return {"test": 3, "iterations": result.iteration, "duration": duration, "status": "PASS"}


async def test_4_no_test_suite():
    """TEST 4: Project without tests."""
    print("\n" + "="*80)
    print("TEST 4: PROJECT WITHOUT TEST SUITE")
    print("="*80)
    
    workspace = Path("D:/po_final_test_notests")
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
        prompt="Create a simple personal landing page with HTML and CSS. No tests needed."
    )
    
    print("\nStarting task...")
    start = time.time()
    result = await engine.run(task)
    duration = time.time() - start
    
    print(f"\nStatus: {result.status}")
    print(f"Iterations: {result.iteration}")
    print(f"Duration: {duration:.1f}s")
    
    assert result.status == TaskState.COMPLETED, f"Task failed: {result.error}"
    html_files = list(workspace.glob("*.html")) or list(workspace.glob("**/*.html"))
    assert len(html_files) > 0, "No HTML created"
    
    print(f"\n✓ TEST 4 PASSED - {result.iteration} iterations, {duration:.1f}s")
    return {"test": 4, "iterations": result.iteration, "duration": duration, "status": "PASS"}


async def test_5_idempotent_directory():
    """TEST 5: Idempotent directory creation."""
    print("\n" + "="*80)
    print("TEST 5: IDEMPOTENT DIRECTORY CREATION")
    print("="*80)
    
    workspace = Path("D:/po_final_test_idem")
    workspace.mkdir(exist_ok=True)
    
    for item in workspace.iterdir():
        if item.is_file():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)
    
    # Pre-create directory
    (workspace / "existing_dir").mkdir()
    
    engine = await setup_engine(workspace)
    
    task = Task(
        id="test-idem-1",
        project_id="p-idem",
        session_id="s-idem",
        workspace_path=str(workspace),
        prompt="Create a directory named 'existing_dir' and add a file 'data.txt' inside it."
    )
    
    print("\nStarting task...")
    start = time.time()
    result = await engine.run(task)
    duration = time.time() - start
    
    print(f"\nStatus: {result.status}")
    print(f"Iterations: {result.iteration}")
    print(f"Duration: {duration:.1f}s")
    
    assert result.status == TaskState.COMPLETED, f"Task failed: {result.error}"
    assert (workspace / "existing_dir" / "data.txt").exists(), "File not created"
    
    print(f"\n✓ TEST 5 PASSED - {result.iteration} iterations, {duration:.1f}s")
    return {"test": 5, "iterations": result.iteration, "duration": duration, "status": "PASS"}


async def main():
    """Run all acceptance tests."""
    print("\n" + "="*80)
    print("PO FINAL ACCEPTANCE TESTS")
    print("Using REAL qwen3-coder:30b via Ollama")
    print("="*80)
    
    results = []
    
    tests = [
        ("Test 1: Elyra Clothing Website", test_1_clothing_website),
        ("Test 2: Windows Shell Commands", test_2_windows_shell),
        ("Test 3: Background Server", test_3_background_server),
        ("Test 4: No Test Suite", test_4_no_test_suite),
        ("Test 5: Idempotent Directory", test_5_idempotent_directory),
    ]
    
    for name, test_func in tests:
        try:
            result = await test_func()
            results.append(result)
        except Exception as e:
            print(f"\n✗ {name} FAILED: {e}")
            results.append({"test": name, "status": "FAIL", "error": str(e)})
    
    print("\n" + "="*80)
    print("FINAL RESULTS")
    print("="*80)
    
    total_duration = sum(r.get("duration", 0) for r in results)
    total_iterations = sum(r.get("iterations", 0) for r in results)
    passed = sum(1 for r in results if r.get("status") == "PASS")
    
    for r in results:
        status = r.get("status", "FAIL")
        iters = r.get("iterations", "N/A")
        dur = r.get("duration", 0)
        print(f"Test {r.get('test')}: {status} ({iters} iterations, {dur:.1f}s)")
    
    print(f"\nPassed: {passed}/{len(results)}")
    print(f"Total iterations: {total_iterations}")
    print(f"Total duration: {total_duration:.1f}s")
    print(f"Average iterations per test: {total_iterations / len(results):.1f}")
    print("="*80 + "\n")
    
    return passed == len(results)


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
