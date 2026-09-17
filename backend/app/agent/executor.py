"""Execute a validated tool call through the registry."""

from __future__ import annotations

from app.tools.base import ToolContext, ToolResult
from app.tools.registry import ToolCall, ToolRegistry


class Executor:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        validated = self.registry.validate_call({"tool": call.tool, "arguments": call.arguments})
        if isinstance(validated, ToolResult):
            return validated
        return await self.registry.execute(validated, context)

    async def execute_approved(self, call: ToolCall, context: ToolContext) -> ToolResult:
        """Execute a tool call that has already been approved by the engine.

        Skips the permission re-check in registry.execute() to avoid the
        fingerprint comparison failing after an approval round-trip.
        The sandbox still enforces workspace boundaries inside each tool handler.
        """
        import time
        from app.events.types import EventType
        from app.tools.registry import _user_message_start, _user_message_done, _safe_args

        validated = self.registry.validate_call({"tool": call.tool, "arguments": call.arguments})
        if isinstance(validated, ToolResult):
            return validated

        await self.registry.bus.emit(
            EventType.TOOL_STARTED,
            task_id=context.task_id,
            tool=validated.tool,
            message=_user_message_start(validated.tool, validated.arguments),
            metadata={"arguments": _safe_args(validated.arguments)},
        )
        started = time.perf_counter()
        result = await self.registry._dispatch(validated, context)
        duration_ms = int((time.perf_counter() - started) * 1000)
        result.data.setdefault("duration_ms", duration_ms)
        await self.registry.bus.emit(
            EventType.TOOL_COMPLETED,
            task_id=context.task_id,
            tool=validated.tool,
            status=result.status,
            message=_user_message_done(validated.tool, result),
            metadata={"code": result.code},
        )
        return result
