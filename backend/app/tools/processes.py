"""Background process management for long-running development servers."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

from app.events.bus import EventBus
from app.events.types import EventType
from app.permissions.sandbox import PathSandbox
from app.tools.base import ToolContext, ToolResult, ToolSpec, ToolStatus


@dataclass
class BackgroundProcess:
    """A long-running background process."""
    id: str
    command: str
    process: asyncio.subprocess.Process
    workspace: str
    started_at: float
    stdout_buffer: list[str]
    stderr_buffer: list[str]
    max_buffer_lines: int = 100

    def is_running(self) -> bool:
        return self.process.returncode is None

    def add_stdout(self, line: str) -> None:
        self.stdout_buffer.append(line)
        if len(self.stdout_buffer) > self.max_buffer_lines:
            self.stdout_buffer.pop(0)

    def add_stderr(self, line: str) -> None:
        self.stderr_buffer.append(line)
        if len(self.stderr_buffer) > self.max_buffer_lines:
            self.stderr_buffer.pop(0)


def start_process_spec() -> ToolSpec:
    return ToolSpec(
        name="start_process",
        description="Start a long-running background process (dev server, watcher, etc.). Returns immediately.",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Command to run"},
                "process_id": {"type": "string", "description": "Unique identifier for this process"},
            },
            "required": ["command", "process_id"],
        },
    )


def stop_process_spec() -> ToolSpec:
    return ToolSpec(
        name="stop_process",
        description="Stop a running background process.",
        parameters={
            "type": "object",
            "properties": {
                "process_id": {"type": "string", "description": "Process identifier to stop"},
            },
            "required": ["process_id"],
        },
    )


def process_status_spec() -> ToolSpec:
    return ToolSpec(
        name="process_status",
        description="Get status and recent output from a background process.",
        parameters={
            "type": "object",
            "properties": {
                "process_id": {"type": "string", "description": "Process identifier to check"},
            },
            "required": ["process_id"],
        },
    )


class ProcessManager:
    """Manages background processes for long-running development servers."""

    def __init__(self, sandbox: PathSandbox, bus: EventBus) -> None:
        self.sandbox = sandbox
        self.bus = bus
        self._processes: dict[str, BackgroundProcess] = {}
        self._reader_tasks: dict[str, tuple[asyncio.Task, asyncio.Task]] = {}

    def specs(self) -> list[ToolSpec]:
        return [start_process_spec(), stop_process_spec(), process_status_spec()]

    async def handle(self, name: str, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        if name == "start_process":
            return await self.start_process(arguments, context)
        if name == "stop_process":
            return await self.stop_process(arguments, context)
        if name == "process_status":
            return await self.process_status(arguments, context)
        return ToolResult(
            status=ToolStatus.INVALID_ARGUMENTS,
            tool=name,
            error="Unknown process management tool",
            code="invalid_arguments"
        )

    async def start_process(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        """Start a background process."""
        command = str(arguments.get("command") or "").strip()
        process_id = str(arguments.get("process_id") or "").strip()

        if not command:
            return ToolResult(
                status=ToolStatus.INVALID_ARGUMENTS,
                tool="start_process",
                error="command is required",
                code="invalid_arguments"
            )

        if not process_id:
            return ToolResult(
                status=ToolStatus.INVALID_ARGUMENTS,
                tool="start_process",
                error="process_id is required",
                code="invalid_arguments"
            )

        if process_id in self._processes:
            existing = self._processes[process_id]
            if existing.is_running():
                return ToolResult(
                    status=ToolStatus.FAILURE,
                    tool="start_process",
                    error=f"Process '{process_id}' is already running",
                    code="already_running"
                )

        cwd = self.sandbox.workspace
        env = os.environ.copy()

        # Use shell execution on Windows
        if sys.platform == "win32":
            shell_command = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
        else:
            shell_command = ["sh", "-c", command]

        await self.bus.emit(
            EventType.COMMAND_STARTED,
            task_id=context.task_id,
            command=command,
            message=f"Starting background process: {process_id}"
        )

        try:
            process = await asyncio.create_subprocess_exec(
                *shell_command,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except FileNotFoundError:
            return ToolResult(
                status=ToolStatus.UNAVAILABLE,
                tool="start_process",
                error="Shell not found",
                code="unavailable"
            )
        except OSError as exc:
            return ToolResult(
                status=ToolStatus.FAILURE,
                tool="start_process",
                error=str(exc),
                code="failure"
            )

        bg_process = BackgroundProcess(
            id=process_id,
            command=command,
            process=process,
            workspace=str(cwd),
            started_at=time.time(),
            stdout_buffer=[],
            stderr_buffer=[]
        )

        self._processes[process_id] = bg_process

        # Start reader tasks
        stdout_task = asyncio.create_task(self._read_stream(process_id, process.stdout, "stdout"))
        stderr_task = asyncio.create_task(self._read_stream(process_id, process.stderr, "stderr"))
        self._reader_tasks[process_id] = (stdout_task, stderr_task)

        # Give process a moment to start
        await asyncio.sleep(0.2)

        if not bg_process.is_running():
            return ToolResult(
                status=ToolStatus.FAILURE,
                tool="start_process",
                error=f"Process exited immediately with code {process.returncode}",
                code="failed_to_start",
                data={
                    "process_id": process_id,
                    "exit_code": process.returncode,
                    "stdout": "\n".join(bg_process.stdout_buffer),
                    "stderr": "\n".join(bg_process.stderr_buffer),
                }
            )

        return ToolResult(
            status=ToolStatus.SUCCESS,
            tool="start_process",
            data={
                "process_id": process_id,
                "command": command,
                "pid": process.pid,
                "status": "running",
                "message": f"Process '{process_id}' started successfully"
            }
        )

    async def stop_process(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        """Stop a background process."""
        process_id = str(arguments.get("process_id") or "").strip()

        if not process_id:
            return ToolResult(
                status=ToolStatus.INVALID_ARGUMENTS,
                tool="stop_process",
                error="process_id is required",
                code="invalid_arguments"
            )

        if process_id not in self._processes:
            return ToolResult(
                status=ToolStatus.FAILURE,
                tool="stop_process",
                error=f"Process '{process_id}' not found",
                code="not_found"
            )

        bg_process = self._processes[process_id]

        if not bg_process.is_running():
            return ToolResult(
                status=ToolStatus.SUCCESS,
                tool="stop_process",
                data={
                    "process_id": process_id,
                    "status": "already_stopped",
                    "exit_code": bg_process.process.returncode
                }
            )

        # Terminate process
        try:
            if sys.platform == "win32":
                bg_process.process.terminate()
            else:
                bg_process.process.send_signal(signal.SIGTERM)
        except ProcessLookupError:
            pass

        # Wait briefly for graceful shutdown
        try:
            await asyncio.wait_for(bg_process.process.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            # Force kill
            try:
                bg_process.process.kill()
                await bg_process.process.wait()
            except ProcessLookupError:
                pass

        # Cancel reader tasks
        if process_id in self._reader_tasks:
            stdout_task, stderr_task = self._reader_tasks[process_id]
            stdout_task.cancel()
            stderr_task.cancel()
            del self._reader_tasks[process_id]

        return ToolResult(
            status=ToolStatus.SUCCESS,
            tool="stop_process",
            data={
                "process_id": process_id,
                "status": "stopped",
                "exit_code": bg_process.process.returncode
            }
        )

    async def process_status(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        """Get status of a background process."""
        process_id = str(arguments.get("process_id") or "").strip()

        if not process_id:
            return ToolResult(
                status=ToolStatus.INVALID_ARGUMENTS,
                tool="process_status",
                error="process_id is required",
                code="invalid_arguments"
            )

        if process_id not in self._processes:
            return ToolResult(
                status=ToolStatus.FAILURE,
                tool="process_status",
                error=f"Process '{process_id}' not found",
                code="not_found"
            )

        bg_process = self._processes[process_id]
        uptime = time.time() - bg_process.started_at

        return ToolResult(
            status=ToolStatus.SUCCESS,
            tool="process_status",
            data={
                "process_id": process_id,
                "command": bg_process.command,
                "status": "running" if bg_process.is_running() else "stopped",
                "pid": bg_process.process.pid,
                "exit_code": bg_process.process.returncode,
                "uptime_seconds": int(uptime),
                "recent_stdout": "\n".join(bg_process.stdout_buffer[-20:]),
                "recent_stderr": "\n".join(bg_process.stderr_buffer[-20:]),
            }
        )

    async def _read_stream(self, process_id: str, stream: asyncio.StreamReader | None, stream_name: str) -> None:
        """Read from process stream and buffer output."""
        if stream is None:
            return

        try:
            while True:
                line = await stream.readline()
                if not line:
                    break

                text = line.decode("utf-8", errors="replace").rstrip()
                if process_id in self._processes:
                    bg_process = self._processes[process_id]
                    if stream_name == "stdout":
                        bg_process.add_stdout(text)
                    else:
                        bg_process.add_stderr(text)
        except asyncio.CancelledError:
            return
        except Exception:
            return

    def cleanup_all(self) -> None:
        """Stop all background processes."""
        for process_id in list(self._processes.keys()):
            bg_process = self._processes[process_id]
            if bg_process.is_running():
                try:
                    bg_process.process.terminate()
                except ProcessLookupError:
                    pass

            if process_id in self._reader_tasks:
                stdout_task, stderr_task = self._reader_tasks[process_id]
                stdout_task.cancel()
                stderr_task.cancel()
