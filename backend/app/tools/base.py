from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ToolStatus(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    PERMISSION_DENIED = "permission_denied"
    INVALID_ARGUMENTS = "invalid_arguments"
    UNAVAILABLE = "unavailable"
    APPROVAL_REQUIRED = "approval_required"
    CANCELLED = "cancelled"


class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]


class ToolResult(BaseModel):
    status: ToolStatus
    tool: str
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    code: str = "ok"

    def as_model_content(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "tool": self.tool,
            "status": self.status,
            "code": self.code,
        }
        if self.error:
            payload["error"] = self.error
        payload.update(self.data)
        return payload


class ToolContext(BaseModel):
    workspace_root: str
    task_id: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)

    model_config = {"arbitrary_types_allowed": True}


ToolHandler = Callable[[dict[str, Any], ToolContext], Awaitable[ToolResult]]


class Tool(BaseModel):
    spec: ToolSpec
    handler: Any = Field(exclude=True)

    async def run(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        return await self.handler(arguments, context)
