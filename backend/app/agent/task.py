from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.agent.state import TaskState


class Task(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    prompt: str
    project_id: str
    workspace_path: str
    session_id: str | None = None
    status: TaskState = TaskState.IDLE
    summary: str = ""
    error: str = ""
    model: str = ""
    user_messages: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    iteration: int = 0
    extra: dict[str, Any] = Field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "prompt": self.prompt,
            "project_id": self.project_id,
            "workspace_path": self.workspace_path,
            "status": self.status,
            "summary": self.summary,
            "error": self.error,
            "model": self.model,
            "iteration": self.iteration,
            "user_messages": self.user_messages[-20:],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class TaskControl:
    def __init__(self) -> None:
        self.cancelled = asyncio.Event()
        self.approval = asyncio.Event()
        self.approval_granted = False
        self.pending_fingerprint: str | None = None

    def cancel(self) -> None:
        self.cancelled.set()

    def grant(self) -> None:
        self.approval_granted = True
        self.approval.set()

    def deny(self) -> None:
        self.approval_granted = False
        self.approval.set()
