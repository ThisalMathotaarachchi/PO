"""Tool registry: validate names/arguments and dispatch execution."""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.events.bus import EventBus
from app.events.types import EventType
from app.permissions.policy import PermissionDecision, PermissionPolicy
from app.tools.base import ToolContext, ToolResult, ToolSpec, ToolStatus
from app.tools.development import DevelopmentTools
from app.tools.filesystem import FilesystemTools
from app.tools.git import GitTools
from app.tools.processes import ProcessManager
from app.tools.search import SearchTools
from app.tools.terminal import TerminalSession


class ToolCall(BaseModel):
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolRegistry:
    def __init__(
        self,
        *,
        filesystem: FilesystemTools,
        search: SearchTools,
        terminal: TerminalSession,
        development: DevelopmentTools,
        git: GitTools,
        processes: ProcessManager,
        policy: PermissionPolicy,
        bus: EventBus,
    ) -> None:
        self.filesystem = filesystem
        self.search = search
        self.terminal = terminal
        self.development = development
        self.git = git
        self.processes = processes
        self.policy = policy
        self.bus = bus
        self._specs = {s.name: s for s in self.all_specs()}

    def all_specs(self) -> list[ToolSpec]:
        return [
            *self.filesystem.specs(),
            *self.search.specs(),
            self.terminal.spec(),
            *self.development.specs(),
            *self.git.specs(),
            *self.processes.specs(),
        ]

    def openai_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            }
            for spec in self.all_specs()
        ]

    def validate_call(self, raw: dict[str, Any]) -> ToolCall | ToolResult:
        try:
            call = ToolCall.model_validate(raw)
        except ValidationError as exc:
            return ToolResult(
                status=ToolStatus.INVALID_ARGUMENTS,
                tool=str(raw.get("tool") or "unknown"),
                error=f"Malformed tool call: {exc}",
                code="invalid_arguments",
            )
        spec = self._specs.get(call.tool)
        if spec is None:
            return ToolResult(
                status=ToolStatus.INVALID_ARGUMENTS,
                tool=call.tool,
                error=f"Unknown tool '{call.tool}'",
                code="invalid_arguments",
            )
        error = _validate_against_schema(call.arguments, spec)
        if error:
            return ToolResult(status=ToolStatus.INVALID_ARGUMENTS, tool=call.tool, error=error, code="invalid_arguments")
        return call

    def check_permission(self, call: ToolCall) -> PermissionDecision:
        return self.policy.evaluate(call.tool, call.arguments)

    async def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        decision = self.check_permission(call)
        if decision.requires_approval:
            return ToolResult(
                status=ToolStatus.APPROVAL_REQUIRED,
                tool=call.tool,
                error=decision.reason,
                code=decision.code,
                data={"level": decision.level, "reason": decision.reason},
            )
        if not decision.allowed:
            return ToolResult(
                status=ToolStatus.PERMISSION_DENIED,
                tool=call.tool,
                error=decision.reason,
                code=decision.code,
            )
        await self.bus.emit(
            EventType.TOOL_STARTED,
            task_id=context.task_id,
            tool=call.tool,
            message=_user_message_start(call.tool, call.arguments),
            metadata={"arguments": _safe_args(call.arguments)},
        )
        started = time.perf_counter()
        result = await self._dispatch(call, context)
        duration_ms = int((time.perf_counter() - started) * 1000)
        result.data.setdefault("duration_ms", duration_ms)
        await self.bus.emit(
            EventType.TOOL_COMPLETED,
            task_id=context.task_id,
            tool=call.tool,
            status=result.status,
            message=_user_message_done(call.tool, result),
            metadata={"code": result.code},
        )
        return result

    async def _dispatch(self, call: ToolCall, context: ToolContext) -> ToolResult:
        name = call.tool
        if name in {s.name for s in self.filesystem.specs()}:
            return await self.filesystem.handle(name, call.arguments, context)
        if name in {s.name for s in self.search.specs()}:
            return await self.search.handle(name, call.arguments, context)
        if name == "run_terminal":
            return await self.terminal.run(call.arguments, context)
        if name in {s.name for s in self.development.specs()}:
            return await self.development.handle(name, call.arguments, context)
        if name in {s.name for s in self.git.specs()}:
            return await self.git.handle(name, call.arguments, context)
        if name in {s.name for s in self.processes.specs()}:
            return await self.processes.handle(name, call.arguments, context)
        return ToolResult(status=ToolStatus.INVALID_ARGUMENTS, tool=name, error="Unknown tool", code="invalid_arguments")

    def cancel_running(self) -> None:
        self.terminal.cancel()
        self.processes.cleanup_all()


def _validate_against_schema(arguments: dict[str, Any], spec: ToolSpec) -> str | None:
    schema = spec.parameters or {}
    required = schema.get("required") or []
    properties = schema.get("properties") or {}
    if not isinstance(arguments, dict):
        return "arguments must be an object"
    for key in required:
        if key not in arguments:
            return f"Missing required argument: {key}"
    for key, value in arguments.items():
        if key not in properties:
            continue
        expected = properties[key].get("type")
        if expected == "string" and not isinstance(value, str):
            return f"Argument {key} must be a string"
        if expected == "integer" and not isinstance(value, int):
            return f"Argument {key} must be an integer"
        if expected == "number" and not isinstance(value, (int, float)):
            return f"Argument {key} must be a number"
        if expected == "boolean" and not isinstance(value, bool):
            return f"Argument {key} must be a boolean"
    return None


def _safe_args(arguments: dict[str, Any]) -> dict[str, Any]:
    out = dict(arguments)
    if "content" in out and isinstance(out["content"], str) and len(out["content"]) > 400:
        out["content"] = out["content"][:400] + "…"
    return out


def _user_message_start(tool: str, arguments: dict[str, Any]) -> str:
    path = arguments.get("path")
    mapping = {
        "list_directory": "Reading project…",
        "read_file": f"Reading {path}…" if path else "Reading file…",
        "search_files": "Searching files…",
        "search_code": "Searching code…",
        "find_symbol": "Finding symbol…",
        "find_references": "Finding references…",
        "write_file": f"Editing {path}…" if path else "Editing file…",
        "create_file": f"Creating {path}…" if path else "Creating file…",
        "run_tests": "Running tests…",
        "run_build": "Running build…",
        "run_linter": "Running linter…",
        "run_terminal": "Running command…",
        "git_status": "Inspecting git status…",
        "git_diff": "Inspecting git diff…",
        "git_log": "Reading git log…",
        "git_branch": "Reading git branches…",
    }
    return mapping.get(tool, f"Using {tool}…")


def _user_message_done(tool: str, result: ToolResult) -> str:
    if result.status == ToolStatus.SUCCESS:
        if tool == "run_tests":
            return "✓ Tests passed."
        return ""
    if result.status == ToolStatus.FAILURE and tool == "run_tests":
        return "Tests failing. Fixing…"
    return result.error or "Tool failed"
