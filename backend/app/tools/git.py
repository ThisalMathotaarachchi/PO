"""Read-only Git inspection against the active workspace."""

from __future__ import annotations

from typing import Any

from app.tools.base import ToolContext, ToolResult, ToolSpec, ToolStatus
from app.tools.terminal import TerminalSession


def git_specs() -> list[ToolSpec]:
    return [
        ToolSpec(name="git_status", description="Show git status for the workspace.", parameters={"type": "object", "properties": {}}),
        ToolSpec(name="git_diff", description="Show git diff. Optional path.", parameters={"type": "object", "properties": {"path": {"type": "string"}}}),
        ToolSpec(name="git_log", description="Show recent git commits.", parameters={"type": "object", "properties": {"limit": {"type": "integer"}}}),
        ToolSpec(name="git_branch", description="Show git branches.", parameters={"type": "object", "properties": {}}),
    ]


class GitTools:
    def __init__(self, terminal: TerminalSession) -> None:
        self.terminal = terminal

    def specs(self) -> list[ToolSpec]:
        return git_specs()

    async def handle(self, name: str, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        commands = {
            "git_status": "git status --short --branch",
            "git_diff": _diff_cmd(arguments),
            "git_log": f"git log -n {int(arguments.get('limit') or 10)} --oneline",
            "git_branch": "git branch -vv",
        }
        command = commands.get(name)
        if not command:
            return ToolResult(status=ToolStatus.INVALID_ARGUMENTS, tool=name, error="Unknown git tool", code="invalid_arguments")
        result = await self.terminal.run({"command": command}, context)
        result.tool = name
        return result


def _diff_cmd(arguments: dict[str, Any]) -> str:
    path = arguments.get("path")
    if path:
        return f"git diff -- {path}"
    return "git diff"
