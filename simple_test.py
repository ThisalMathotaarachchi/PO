"""Simple direct test without pytest"""
import asyncio
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

async def main():
    workspace = Path("D:/po_stress_test")
    workspace.mkdir(exist_ok=True)
    
    # Clean workspace
    for item in workspace.iterdir():
        if item.is_file():
            item.unlink()
        elif item.is_dir():
            import shutil
            shutil.rmtree(item)
    
    # Database outside workspace
    db_dir = Path(tempfile.gettempdir()) / "po_test_dbs"
    db_dir.mkdir(exist_ok=True)
    test_db_path = db_dir / "po_stress_test.db"
    if test_db_path.exists():
        test_db_path.unlink()
    
    settings = Settings(
        database_path=str(test_db_path),
        agent_task_timeout_seconds=600.0,  # 10 minutes for faster iteration
        agent_max_iterations=50,
        command_timeout_seconds=120.0,
    )
    
    db = Database(settings.resolve_database_path())
    await db.initialize()
    memory = MemoryManager(db)
    bus = EventBus()
    
    provider = OllamaProvider(
        host=settings.ollama_host,
        timeout=settings.ollama_timeout_seconds
    )
    
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
    index = ProjectIndex(memory=memory, ignore_directories=list(settings.ignore_directories), max_file_bytes=settings.index_max_file_bytes)
    context = ContextEngine(index=index, memory=memory)
    
    engine = AgentEngine(
        provider=provider,
        tools=registry,
        memory=memory,
        bus=bus,
        model_registry=model_registry,
        router=router,
        context=context,
        max_iterations=settings.agent_max_iterations,
        task_timeout=settings.agent_task_timeout_seconds,
    )
    
    task = Task(
        id="simple-calc-1",
        project_id="p-simple",
        session_id="s-simple",
        workspace_path=str(workspace),
        prompt=(
            "Create a simple Python calculator.\n\n"
            "Requirements:\n"
            "1. Create src/calculator/ directory\n"
            "2. Create src/calculator/calc.py with add, subtract, multiply, divide functions\n"
            "3. Division by zero must raise ValueError\n"
            "4. Create tests/ directory\n"
            "5. Create tests/test_calc.py with pytest tests\n"
            "6. Run pytest to verify\n"
            "7. If tests fail, fix and rerun\n"
        ),
    )
    
    print("Starting task...")
    result = await engine.run(task)
    
    print(f"\nStatus: {result.status}")
    print(f"Summary: {result.summary}")
    print(f"Iterations: {result.iteration}")
    
    if result.status == TaskState.COMPLETED:
        # Verify
        calc_py = workspace / "src" / "calculator" / "calc.py"
        test_py = workspace / "tests" / "test_calc.py"
        if calc_py.exists() and test_py.exists():
            print("\n✓ Files created successfully")
            print(f"✓ calc.py: {calc_py.stat().st_size} bytes")
            print(f"✓ test_calc.py: {test_py.stat().st_size} bytes")
            return 0
        else:
            print("\n✗ Expected files not found")
            return 1
    else:
        print(f"\n✗ Task failed: {result.error}")
        return 1

if __name__ == "__main__":
    exit(asyncio.run(main()))
