"""Autonomous agent loop: understand → tools → observe → reassess → complete."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.agent.executor import Executor
from app.agent.planner import AgentAction, AgentActionType, Planner
from app.agent.state import TERMINAL_STATES, TaskState, state_for_tool
from app.agent.task import Task, TaskControl
from app.agent.verification import verify_completion
from app.context.retrieval import ContextEngine
from app.events.bus import EventBus
from app.events.types import EventType
from app.logging_setup import get_logger, log_event
from app.memory.manager import MemoryManager
from app.models.base import ChatMessage, ModelProvider, ModelRole, ProviderError
from app.models.registry import ModelRegistry
from app.models.router import ModelRouter
from app.tools.base import ToolContext, ToolResult, ToolStatus
from app.tools.registry import ToolCall, ToolRegistry

SYSTEM_PROMPT = """You are Po, an autonomous software development agent. Your role is to complete tasks efficiently using tools.

RESPONSE FORMAT:
Always output exactly ONE JSON object per response:

Tool call:
{"tool": "tool_name", "arguments": {...}}

Task complete:
{"complete": true, "summary": "brief statement of what was done"}

EXECUTION RULES:
1. ONE tool call per response - wait for results before the next action
2. Plan internally but execute incrementally - don't narrate your plan
3. Avoid redundant operations:
   - Don't re-read unchanged files
   - Don't re-list unchanged directories  
   - Don't re-run successful commands without reason
   - Don't recreate existing directories
4. After filesystem operations, verify ONCE if needed, then proceed
5. Use appropriate verification:
   - For static sites: check files exist, structure is correct
   - For code projects: run tests if they exist
   - Don't force tests on projects without test suites
6. Stop when acceptance criteria are met - don't continue exploring unnecessarily

COMPLETION CRITERIA:
Mark complete when:
- Required files/functionality exist
- Verification passed (when applicable)
- Task objective is satisfied

Do NOT:
- Repeatedly inspect/verify after success
- Narrate every action with explanations
- Think aloud or show reasoning
- Wrap JSON in markdown blocks
- Return multiple concatenated JSON objects
- Repeat failed actions without changes
- Override user requirements with unrelated context

Work efficiently. Output only the JSON object."""


class AgentEngine:
    def __init__(
        self,
        *,
        provider: ModelProvider,
        registry: ModelRegistry,
        router: ModelRouter,
        tools: ToolRegistry,
        context: ContextEngine,
        memory: MemoryManager,
        bus: EventBus,
        max_iterations: int,
    ) -> None:
        self.provider = provider
        self.model_registry = registry
        self.router = router
        self.tools = tools
        self.context = context
        self.memory = memory
        self.bus = bus
        self.max_iterations = max_iterations
        self.planner = Planner()
        self.executor = Executor(tools)
        self._log = get_logger("agent")
        self._controls: dict[str, TaskControl] = {}
        self._tasks: dict[str, Task] = {}

    def get_task(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def control(self, task_id: str) -> TaskControl | None:
        return self._controls.get(task_id)

    async def cancel(self, task_id: str) -> Task | None:
        control = self._controls.get(task_id)
        if control:
            control.cancel()
        self.tools.cancel_running()
        task = self._tasks.get(task_id)
        if task and task.status not in TERMINAL_STATES:
            await self._set_state(task, TaskState.CANCELLED, user_message="Cancelled.")
            await self.bus.emit(EventType.TASK_CANCELLED, task_id=task_id, message="Cancelled.", status="cancelled")
            await self.memory.update_task(task_id, status=TaskState.CANCELLED, summary=task.summary)
        return task

    async def approve(self, task_id: str, granted: bool) -> Task | None:
        control = self._controls.get(task_id)
        task = self._tasks.get(task_id)
        if not control or not task:
            return task
        if granted:
            if control.pending_fingerprint:
                self.tools.policy.approve(control.pending_fingerprint)
            control.grant()
            await self.bus.emit(EventType.APPROVAL_GRANTED, task_id=task_id, message="Approved")
        else:
            control.deny()
            await self.bus.emit(EventType.APPROVAL_DENIED, task_id=task_id, message="Denied")
        return task

    async def run(self, task: Task) -> Task:
        control = TaskControl()
        self._controls[task.id] = control
        self._tasks[task.id] = task
        started = time.perf_counter()
        try:
            # No arbitrary task timeout - run until completion or cancellation
            await self._run_loop(task, control)
        except ProviderError as exc:
            await self._fail(task, str(exc), code=exc.code)
        except asyncio.CancelledError:
            await self.cancel(task.id)
        except Exception as exc:
            self._log.exception("agent crash")
            await self._fail(task, str(exc))
        finally:
            log_event(self._log, "task finished", task_id=task.id, status=task.status, ms=int((time.perf_counter() - started) * 1000))
        return task

    async def _run_loop(self, task: Task, control: TaskControl) -> None:
        await self._set_state(task, TaskState.UNDERSTANDING, user_message="Understanding the request…")
        await self.bus.emit(EventType.TASK_STARTED, task_id=task.id, message="Starting task")
        await self.memory.create_task(
            task_id=task.id,
            project_id=task.project_id,
            session_id=task.session_id,
            prompt=task.prompt,
            status=task.status,
        )

        try:
            models = await self.model_registry.refresh()
        except ProviderError as exc:
            await self._fail(task, str(exc), code=exc.code)
            return

        selected = self.router.select(models, prompt=task.prompt)
        task.model = selected.id
        await self.memory.update_task(task.id, model=selected.id)
        await self.bus.emit(
            EventType.MODEL_SELECTED,
            task_id=task.id,
            message=f"Using {selected.id}",
            metadata={"model": selected.id, "family": selected.family},
        )

        profile, _relevant, context_text = await self.context.gather(
            project_id=task.project_id,
            workspace=Path(task.workspace_path),
            prompt=task.prompt,
            task_id=task.id,
        )
        await self.memory.add_memory(task.project_id, "stack", profile.summary)

        await self._set_state(task, TaskState.PLANNING)

        messages: list[ChatMessage] = [
            ChatMessage(role=ModelRole.SYSTEM, content=SYSTEM_PROMPT),
            ChatMessage(
                role=ModelRole.USER,
                content=(
                    f"CURRENT TASK (your only focus):\n{task.prompt}\n\n"
                    f"Workspace: {task.workspace_path}\n\n"
                    f"{context_text}\n\n"
                    "Complete this task efficiently using tools. Output JSON only."
                ),
            ),
        ]

        recent_failures: list[str] = []
        malformed_retries = 0
        recent_operations: list[tuple[str, str]] = []  # Track (tool, key) pairs to detect redundancy
        files_created: set[str] = set()  # Track files created during task
        files_modified: set[str] = set()  # Track files modified during task

        for iteration in range(1, self.max_iterations + 1):
            if control.cancelled.is_set():
                await self.cancel(task.id)
                return
            task.iteration = iteration
            log_event(self._log, "iteration", task_id=task.id, iteration=iteration, state=task.status)

            # Log model request for debugging
            prompt_length = sum(len(m.content or "") for m in messages)
            self._log.info(f"Model request: task={task.id} iter={iteration} messages={len(messages)} prompt_chars={prompt_length}")
            
            request_start = time.perf_counter()
            response = await self.provider.chat(
                messages,
                model=selected.id,
                tools=self.tools.openai_tools(),
                family=selected.family,
                cancel_event=control.cancelled,
            )
            request_duration = time.perf_counter() - request_start
            
            await self.memory.record_model_usage(
                task.id, selected.id, response.prompt_tokens, response.completion_tokens
            )
            
            # Log model response metrics
            self._log.info(
                f"Model response: task={task.id} iter={iteration} duration={request_duration:.2f}s "
                f"prompt_tokens={response.prompt_tokens} completion_tokens={response.completion_tokens}"
            )

            action = self.planner.parse(response)
            if action.type == AgentActionType.MALFORMED:
                malformed_retries += 1
                if malformed_retries > 3:
                    await self._fail(task, "Model returned malformed tool calls repeatedly")
                    return
                messages.append(ChatMessage(role=ModelRole.ASSISTANT, content=response.content or action.raw))
                messages.append(
                    ChatMessage(
                        role=ModelRole.USER,
                        content=action.repair_hint or "Return valid JSON for a tool call.",
                    )
                )
                continue
            malformed_retries = 0

            if action.type == AgentActionType.COMPLETE:
                await self._set_state(task, TaskState.VERIFYING)
                summary = action.summary or "Done."
                
                # Verify completion before accepting
                verification = verify_completion(
                    workspace_path=task.workspace_path,
                    task_prompt=task.prompt,
                    files_created=files_created,
                    files_modified=files_modified
                )
                
                if not verification.passed:
                    # Verification failed - inform model and continue
                    self._log.warning(f"Completion verification failed: {verification.message}")
                    messages.append(ChatMessage(
                        role=ModelRole.ASSISTANT,
                        content=response.content or '{"complete": true}'
                    ))
                    messages.append(ChatMessage(
                        role=ModelRole.USER,
                        content=f"Verification failed: {verification.message}\n\nPlease complete the missing work and verify before marking complete."
                    ))
                    await self._set_state(task, TaskState.EXECUTING)
                    continue
                
                # Verification passed - complete the task
                task.summary = summary
                await self._set_state(task, TaskState.COMPLETED, user_message=summary if summary.endswith(".") else summary + ".")
                await self.bus.emit(EventType.TASK_COMPLETED, task_id=task.id, message=task.summary or "Done.")
                await self.memory.update_task(task.id, status=TaskState.COMPLETED, summary=task.summary)
                await self.memory.add_memory(task.project_id, "task_summary", f"{task.prompt[:80]} → {task.summary}")
                return

            assert action.tool_call is not None
            call = action.tool_call
            
            # Validate non-empty paths for filesystem operations
            if call.tool in {"create_directory", "delete_directory", "write_file", "read_file", "delete_file"}:
                path_arg = str(call.arguments.get("path") or "").strip()
                if not path_arg:
                    messages.append(_assistant_tool(call, response.content))
                    messages.append(ChatMessage(
                        role=ModelRole.TOOL,
                        content=json.dumps({"tool": call.tool, "status": "invalid", "error": "path cannot be empty"}),
                        name=call.tool
                    ))
                    continue
            
            # Detect redundant operations
            operation_key = _operation_key(call)
            if operation_key and recent_operations.count((call.tool, operation_key)) >= 2:
                self._log.warning(f"Redundant operation detected: {call.tool} on {operation_key}")
                # Inform model to try something different
                messages.append(_assistant_tool(call, response.content))
                messages.append(ChatMessage(
                    role=ModelRole.TOOL,
                    content=json.dumps({
                        "tool": call.tool,
                        "status": "redundant",
                        "message": f"This operation was already performed recently. Try a different approach or proceed to the next step."
                    }),
                    name=call.tool
                ))
                continue
            
            signature = f"{call.tool}:{json.dumps(call.arguments, sort_keys=True, default=str)}"
            if recent_failures.count(signature) >= 3:
                messages.append(
                    ChatMessage(
                        role=ModelRole.USER,
                        content="That action failed repeatedly. Try a different approach. Do not repeat it unchanged.",
                    )
                )
                recent_failures.append("__nudge__")
                continue

            decision = self.tools.check_permission(call)
            if not decision.allowed and not decision.requires_approval:
                result = ToolResult(
                    status=ToolStatus.PERMISSION_DENIED,
                    tool=call.tool,
                    error=decision.reason,
                    code=decision.code,
                )
                log_event(
                    self._log,
                    "tool blocked",
                    task_id=task.id,
                    tool=call.tool,
                    reason=decision.reason,
                )
                messages.append(_assistant_tool(call, response.content))
                messages.append(_tool_message(result))
                continue

            context = ToolContext(workspace_root=task.workspace_path, task_id=task.id)
            if call.tool in {"write_file", "create_file"}:
                await self.bus.emit(EventType.FIX_STARTED, task_id=task.id, path=str(call.arguments.get("path") or ""), message="Applying fix…")

            log_event(
                self._log,
                "tool execute",
                task_id=task.id,
                iteration=iteration,
                tool=call.tool,
                path=str(call.arguments.get("path") or call.arguments.get("command") or ""),
            )
            tool_start = time.perf_counter()
            try:
                result = await self.executor.execute_approved(call, context)
            except Exception as tool_exc:
                import traceback as _tb
                log_event(
                    self._log,
                    "tool execution exception",
                    task_id=task.id,
                    iteration=iteration,
                    tool=call.tool,
                    arguments={k: v for k, v in call.arguments.items() if k != "content"},
                    exc_type=type(tool_exc).__name__,
                    exc_message=str(tool_exc),
                    traceback=_tb.format_exc(),
                )
                raise
            tool_duration = time.perf_counter() - tool_start
            
            log_event(
                self._log,
                "tool result",
                task_id=task.id,
                tool=call.tool,
                status=str(result.status),
                duration_ms=int(tool_duration * 1000),
                path=str(result.data.get("path") or call.arguments.get("path") or ""),
                error=result.error or "",
            )
            await self.memory.record_tool_call(
                task.id, call.tool, call.arguments, result.status, result.as_model_content(), int(result.data.get("duration_ms") or 0)
            )
            await self.memory.add_step(task.id, iteration, task.status, call.tool, _user_line(call, result))

            # Track operations for redundancy detection
            if operation_key:
                recent_operations.append((call.tool, operation_key))
                # Keep only last 10 operations
                if len(recent_operations) > 10:
                    recent_operations.pop(0)
            
            # Track file creation/modification for verification
            if result.status == ToolStatus.SUCCESS:
                if call.tool in {"write_file", "create_file"}:
                    file_path = str(call.arguments.get("path", ""))
                    if file_path:
                        # Store relative path from workspace
                        try:
                            rel_path = Path(file_path).relative_to(task.workspace_path)
                            if Path(task.workspace_path, file_path).exists():
                                files_created.add(str(rel_path).replace('\\', '/'))
                        except ValueError:
                            # Path might already be relative
                            if Path(task.workspace_path, file_path).exists():
                                files_created.add(file_path.replace('\\', '/'))
                elif call.tool in {"modify_file", "update_file"}:
                    file_path = str(call.arguments.get("path", ""))
                    if file_path:
                        try:
                            rel_path = Path(file_path).relative_to(task.workspace_path)
                            if Path(task.workspace_path, file_path).exists():
                                files_modified.add(str(rel_path).replace('\\', '/'))
                        except ValueError:
                            if Path(task.workspace_path, file_path).exists():
                                files_modified.add(file_path.replace('\\', '/'))

            if result.status == ToolStatus.SUCCESS:
                recent_failures = [s for s in recent_failures if s != signature]
            else:
                recent_failures.append(signature)
                await self.bus.emit(EventType.ERROR_DETECTED, task_id=task.id, tool=call.tool, message=result.error or "Tool failed", status="error")

            new_state = state_for_tool(call.tool, result.status == ToolStatus.SUCCESS)
            if result.status != ToolStatus.SUCCESS and call.tool in {"run_tests", "run_build", "run_terminal"}:
                new_state = TaskState.DEBUGGING
            await self._set_state(task, new_state, user_message=_user_line(call, result) or None)

            messages.append(_assistant_tool(call, response.content))
            messages.append(_tool_message(result))
            
            # Context management: summarize old tool results to prevent unbounded growth
            if len(messages) > 20:
                messages = _condense_messages(messages)

        await self._fail(task, f"Reached iteration limit ({self.max_iterations})")

    async def _set_state(self, task: Task, state: TaskState, user_message: str | None = None) -> None:
        task.status = state
        task.updated_at = datetime.now(timezone.utc)
        if user_message:
            task.user_messages.append(user_message)
            await self.bus.emit(EventType.USER_MESSAGE, task_id=task.id, message=user_message)
        await self.bus.emit(EventType.STATE_CHANGED, task_id=task.id, message=state, metadata={"state": state})
        await self.memory.update_task(task.id, status=state, summary=task.summary)

    async def _fail(self, task: Task, error: str, code: str = "error") -> None:
        task.error = error
        task.summary = error
        await self._set_state(task, TaskState.ERROR, user_message=error)
        await self.bus.emit(EventType.TASK_FAILED, task_id=task.id, message=error, status="error", metadata={"code": code})
        await self.memory.update_task(task.id, status=TaskState.ERROR, error=error, summary=error)


def _assistant_tool(call: ToolCall, content: str) -> ChatMessage:
    return ChatMessage(
        role=ModelRole.ASSISTANT,
        content=content or json.dumps({"tool": call.tool, "arguments": call.arguments}),
        tool_calls=[{"tool": call.tool, "arguments": call.arguments}],
    )


def _tool_message(result: ToolResult) -> ChatMessage:
    payload = result.as_model_content()
    # Keep tool payloads bounded
    text = json.dumps(payload, default=str)
    if len(text) > 12_000:
        payload = {k: payload[k] for k in payload if k in {"tool", "status", "code", "error", "path", "exit_code"}}
        payload["truncated"] = True
        text = json.dumps(payload, default=str)
    return ChatMessage(role=ModelRole.TOOL, content=text, name=result.tool)


def _user_line(call: ToolCall, result: ToolResult) -> str:
    if result.status == ToolStatus.SUCCESS:
        if call.tool == "run_tests":
            return "✓ Tests passed."
        if call.tool == "list_directory":
            return "Reading project…"
        if call.tool in {"write_file", "create_file"}:
            return f"Editing {call.arguments.get('path')}…"
        if call.tool == "read_file":
            return f"Reading {call.arguments.get('path')}…"
        return ""
    if call.tool == "run_tests":
        return "Tests failing. Fixing…"
    return result.error or ""


def _operation_key(call: ToolCall) -> str | None:
    """Generate a key for detecting redundant operations."""
    if call.tool in {"read_file", "file_exists", "list_directory"}:
        return str(call.arguments.get("path") or "")
    if call.tool in {"write_file", "create_file"}:
        return str(call.arguments.get("path") or "")
    if call.tool == "run_tests":
        return call.tool  # Any test run
    if call.tool == "run_terminal":
        return str(call.arguments.get("command") or "")
    return None


def _condense_messages(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Condense message history to prevent unbounded context growth.
    Keep system prompt, initial user request, and recent messages."""
    if len(messages) <= 20:
        return messages
    
    # Keep: system prompt (index 0), initial request (index 1), last 15 messages
    condensed = messages[:2] + [
        ChatMessage(
            role=ModelRole.USER,
            content="[Previous tool results summarized to save context. Continue with the task.]"
        )
    ] + messages[-15:]
    
    return condensed
