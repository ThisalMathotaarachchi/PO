from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    ok: bool
    database: bool
    ollama: dict[str, Any]
    version: str


class WorkspaceCreate(BaseModel):
    path: str
    name: str | None = None


class WorkspaceOpen(BaseModel):
    path: str
    name: str | None = None


class WorkspaceView(BaseModel):
    id: str
    path: str
    name: str


class TaskCreate(BaseModel):
    prompt: str
    workspace_path: str | None = None


class TaskView(BaseModel):
    id: str
    prompt: str
    status: str
    summary: str = ""
    error: str = ""
    model: str = ""
    iteration: int = 0
    user_messages: list[str] = Field(default_factory=list)
    project_id: str = ""
    workspace_path: str = ""


class ApprovalBody(BaseModel):
    granted: bool = True
