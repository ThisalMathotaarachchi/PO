from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class EventType(StrEnum):
    TASK_STARTED = "TASK_STARTED"
    MODEL_SELECTED = "MODEL_SELECTED"
    CONTEXT_STARTED = "CONTEXT_STARTED"
    CONTEXT_COMPLETED = "CONTEXT_COMPLETED"
    FILE_READ = "FILE_READ"
    SEARCH_STARTED = "SEARCH_STARTED"
    SEARCH_COMPLETED = "SEARCH_COMPLETED"
    TOOL_STARTED = "TOOL_STARTED"
    TOOL_COMPLETED = "TOOL_COMPLETED"
    FILE_CHANGED = "FILE_CHANGED"
    COMMAND_STARTED = "COMMAND_STARTED"
    COMMAND_COMPLETED = "COMMAND_COMPLETED"
    TEST_STARTED = "TEST_STARTED"
    TEST_COMPLETED = "TEST_COMPLETED"
    ERROR_DETECTED = "ERROR_DETECTED"
    FIX_STARTED = "FIX_STARTED"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_FAILED = "TASK_FAILED"
    TASK_CANCELLED = "TASK_CANCELLED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    APPROVAL_GRANTED = "APPROVAL_GRANTED"
    APPROVAL_DENIED = "APPROVAL_DENIED"
    STATE_CHANGED = "STATE_CHANGED"
    USER_MESSAGE = "USER_MESSAGE"


class AgentEvent(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    type: EventType
    task_id: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    message: str = ""
    status: str = "ok"
    path: str | None = None
    tool: str | None = None
    command: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
