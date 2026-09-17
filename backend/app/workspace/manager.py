"""Active workspace tracking and validation."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field

from app.memory.manager import MemoryManager
from app.permissions.sandbox import PathSandbox


class WorkspaceError(ValueError):
    pass


class Workspace(BaseModel):
    id: str
    path: str
    name: str
    exists: bool = True

    @property
    def root(self) -> Path:
        return Path(self.path)


class WorkspaceManager:
    def __init__(self, memory: MemoryManager) -> None:
        self.memory = memory
        self._active: Workspace | None = None

    @property
    def active(self) -> Workspace | None:
        return self._active

    def require_active(self) -> Workspace:
        if self._active is None:
            raise WorkspaceError("No active workspace")
        return self._active

    def sandbox(self) -> PathSandbox:
        ws = self.require_active()
        return PathSandbox(ws.root)

    def validate_path(self, path: str | Path) -> Path:
        root = Path(path).expanduser()
        if not root.is_absolute():
            root = Path.cwd() / root
        root = root.resolve()
        if root.exists() and not root.is_dir():
            raise WorkspaceError("Workspace path is not a directory")
        # Refuse operating on clearly unsafe roots
        if root.drive and root == Path(root.drive + os.sep):
            raise WorkspaceError("Refusing to use a drive root as a workspace")
        home = Path.home().resolve()
        if root == home:
            raise WorkspaceError("Refusing to use the user home directory as a workspace")
        return root

    async def create_project(self, path: str, name: str | None = None) -> Workspace:
        root = self.validate_path(path)
        root.mkdir(parents=True, exist_ok=True)
        return await self.open_project(str(root), name=name)

    async def open_project(self, path: str, name: str | None = None) -> Workspace:
        root = self.validate_path(path)
        if not root.exists():
            raise WorkspaceError("Workspace does not exist")
        path_str = str(root)
        existing = await self.memory.get_project_by_path(path_str)
        project_id = existing["id"] if existing else uuid4().hex
        display = name or (existing["name"] if existing else root.name)
        await self.memory.upsert_project(project_id, path_str, display)
        ws = Workspace(id=project_id, path=path_str, name=display, exists=True)
        self._active = ws
        return ws

    def set_active(self, workspace: Workspace) -> None:
        self._active = workspace
