"""Application service container. API routes use this; they do not contain agent logic."""

from __future__ import annotations

from pathlib import Path

from app.config.settings import Settings
from app.context.indexing import ProjectIndex
from app.context.retrieval import ContextEngine
from app.events.bus import EventBus
from app.hooks.manager import HookManager
from app.memory.database import Database
from app.memory.manager import MemoryManager
from app.models.base import ModelProvider
from app.models.ollama import OllamaProvider
from app.models.registry import ModelRegistry
from app.models.router import ModelRouter
from app.agent.engine import AgentEngine
from app.permissions.policy import PermissionPolicy
from app.permissions.sandbox import PathSandbox
from app.tools.development import DevelopmentTools
from app.tools.filesystem import FilesystemTools
from app.tools.git import GitTools
from app.tools.processes import ProcessManager
from app.tools.registry import ToolRegistry
from app.tools.search import SearchTools
from app.tools.terminal import TerminalSession
from app.workspace.manager import Workspace, WorkspaceManager


class AppContainer:
    def __init__(self, settings: Settings, db: Database, provider: ModelProvider | None = None) -> None:
        self.settings = settings
        self.db = db
        self.bus = EventBus()
        self.memory = MemoryManager(db)
        self.workspace = WorkspaceManager(self.memory)
        self.provider: ModelProvider = provider or OllamaProvider(
            settings.ollama_host,
            settings.ollama_timeout_seconds,
            settings.ollama_generation_timeout_seconds,
        )
        self.model_registry = ModelRegistry(self.provider)
        self.router = ModelRouter(preferred=settings.preferred_model)
        self.index = ProjectIndex(self.memory, settings.ignore_directories, settings.index_max_file_bytes)
        self.context = ContextEngine(self.index, self.memory, self.bus, settings.ignore_directories)
        self.engine: AgentEngine | None = None
        self.file_snapshots: dict[str, str] = {}
        self.bus.subscribe(self._persist_event)

    def tools_for(self, workspace: Workspace) -> ToolRegistry:
        sandbox = PathSandbox(Path(workspace.path))
        policy = PermissionPolicy(sandbox)
        bus = self.bus
        settings = self.settings
        fs = FilesystemTools(
            sandbox,
            bus,
            read_limit_bytes=settings.file_read_limit_bytes,
            ignore_directories=settings.ignore_directories,
            snapshots=self.file_snapshots,
        )
        search = SearchTools(
            sandbox,
            bus,
            ignore_directories=settings.ignore_directories,
            max_results=settings.search_max_results,
            max_file_bytes=settings.index_max_file_bytes,
        )
        terminal = TerminalSession(
            sandbox,
            bus,
            default_timeout=settings.command_timeout_seconds,
            output_limit=settings.command_output_limit_bytes,
        )
        development = DevelopmentTools(terminal, Path(workspace.path), bus)
        git = GitTools(terminal)
        processes = ProcessManager(sandbox, bus)
        return ToolRegistry(
            filesystem=fs,
            search=search,
            terminal=terminal,
            development=development,
            git=git,
            processes=processes,
            policy=policy,
            bus=bus,
        )

    def engine_for(self, workspace: Workspace, provider: ModelProvider | None = None) -> AgentEngine:
        from app.agent.executor import Executor

        tools = self.tools_for(workspace)

        # Set up hook manager for this workspace
        hook_mgr = HookManager(self.memory, workspace.path)
        hook_mgr.set_tools(tools)

        if self.engine is None:
            self.engine = AgentEngine(
                provider=provider or self.provider,
                registry=self.model_registry,
                router=self.router,
                tools=tools,
                context=self.context,
                memory=self.memory,
                bus=self.bus,
                max_iterations=self.settings.agent_max_iterations,
            )
        else:
            self.engine.tools = tools
            self.engine.executor = Executor(tools)
            if provider is not None:
                self.engine.provider = provider
                self.engine.model_registry = ModelRegistry(provider)

        # Subscribe hook manager to bus (replace previous subscription for this workspace)
        # Use a wrapper that loads hooks before first use
        self._hook_mgr = hook_mgr
        # Register as a general listener; load will happen lazily on first event
        self._hook_mgr_loaded = False

        def _hook_listener(event):  # type: ignore[type-arg]
            import asyncio
            coro = self._dispatch_hook(event)
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(coro)
                else:
                    loop.run_until_complete(coro)
            except Exception:
                pass

        # Remove previous hook listener if any, then add new one
        listeners = self.bus._listeners.get(None, [])
        self.bus._listeners[None] = [
            l for l in listeners if not getattr(l, "_is_hook_listener", False)
        ]
        _hook_listener._is_hook_listener = True  # type: ignore[attr-defined]
        self.bus.subscribe(_hook_listener)

        return self.engine

    async def _dispatch_hook(self, event) -> None:  # type: ignore[type-arg]
        """Load hooks once, then forward each event."""
        if not self._hook_mgr_loaded:
            ws = self.workspace.active
            if ws:
                await self._hook_mgr.load(ws.id)
            self._hook_mgr_loaded = True
        await self._hook_mgr.handle_event(event)

    async def _persist_event(self, event) -> None:  # noqa: ANN001
        await self.db.insert_event(event.task_id, event.type, event.to_record())
