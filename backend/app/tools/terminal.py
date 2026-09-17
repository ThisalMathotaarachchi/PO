"""Workspace-scoped command execution with Windows-safe subprocess handling."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import time
from typing import Any

from app.events.bus import EventBus
from app.events.types import EventType
from app.permissions.sandbox import PathSandbox
from app.tools.base import ToolContext, ToolResult, ToolSpec, ToolStatus

_ALLOWED_PREFIXES = (
    "python",
    "py",
    "pytest",
    "pip",
    "npm",
    "npx",
    "node",
    "git",
    "pnpm",
    "yarn",
    "tsc",
    "eslint",
    "ruff",
    "uv",
    "cargo",
    "go",
    "dotnet",
    "vitest",
    "vite",
)


def terminal_spec() -> ToolSpec:
    return ToolSpec(
        name="run_terminal",
        description="Run a development command in the workspace. Prefer project-local tools.",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "number"},
            },
            "required": ["command"],
        },
    )


def split_command(command: str) -> list[str]:
    """Split a command string in a Windows-friendly way without using bash."""
    import shlex

    return shlex.split(command, posix=(os.name != "nt"))


class TerminalSession:
    def __init__(
        self,
        sandbox: PathSandbox,
        bus: EventBus,
        *,
        default_timeout: float,
        output_limit: int,
    ) -> None:
        self.sandbox = sandbox
        self.bus = bus
        self.default_timeout = default_timeout
        self.output_limit = output_limit
        self._process: asyncio.subprocess.Process | None = None
        self._cancelled = False

    def spec(self) -> ToolSpec:
        return terminal_spec()

    def cancel(self) -> None:
        self._cancelled = True
        proc = self._process
        if proc and proc.returncode is None:
            _terminate_process(proc)

    async def run(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        # Support both command string and argv array for compatibility
        argv = arguments.get("argv")
        if argv and isinstance(argv, list):
            # Direct argv execution (for tests)
            command_str = str(arguments.get("command") or " ".join(argv))
            shell_command = argv
            use_shell = False
        else:
            command_str = str(arguments.get("command") or "").strip()
            if not command_str:
                return ToolResult(status=ToolStatus.INVALID_ARGUMENTS, tool="run_terminal", error="command is required", code="invalid_arguments")
            # Execute through shell on Windows (PowerShell) to handle shell commands
            if sys.platform == "win32":
                shell_command = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command_str]
            else:
                shell_command = ["sh", "-c", command_str]
            use_shell = True
        
        self._cancelled = False
        timeout = float(arguments.get("timeout") or self.default_timeout)
        cwd = self.sandbox.workspace
        env = os.environ.copy()
        
        await self.bus.emit(
            EventType.COMMAND_STARTED,
            task_id=context.task_id,
            command=command_str,
            message=f"Running `{_short(command_str)}`…",
        )
        started = time.perf_counter()
        
        try:
            self._process = await asyncio.create_subprocess_exec(
                *shell_command,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            try:
                stdout_b, stderr_b = await asyncio.wait_for(self._process.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                _terminate_process(self._process)
                try:
                    await asyncio.wait_for(self._process.communicate(), timeout=2)
                except Exception:
                    pass
                await self.bus.emit(
                    EventType.COMMAND_COMPLETED,
                    task_id=context.task_id,
                    command=command_str,
                    status="timeout",
                    message="Command timed out",
                )
                return ToolResult(
                    status=ToolStatus.TIMEOUT,
                    tool="run_terminal",
                    error=f"Command timed out after {timeout}s",
                    code="timeout",
                    data={"command": command_str, "timeout": timeout, "cwd": str(cwd)},
                )
        except FileNotFoundError:
            return ToolResult(
                status=ToolStatus.UNAVAILABLE,
                tool="run_terminal",
                error=f"Shell not found" if use_shell else f"Executable not found: {shell_command[0]}",
                code="unavailable",
            )
        except OSError as exc:
            return ToolResult(status=ToolStatus.FAILURE, tool="run_terminal", error=str(exc), code="failure")

        duration_ms = int((time.perf_counter() - started) * 1000)
        if self._cancelled:
            return ToolResult(status=ToolStatus.CANCELLED, tool="run_terminal", error="Cancelled", code="cancelled")

        stdout = _clip(stdout_b.decode("utf-8", errors="replace"), self.output_limit)
        stderr = _clip(stderr_b.decode("utf-8", errors="replace"), self.output_limit)
        code = self._process.returncode if self._process else -1
        status = ToolStatus.SUCCESS if code == 0 else ToolStatus.FAILURE
        await self.bus.emit(
            EventType.COMMAND_COMPLETED,
            task_id=context.task_id,
            command=command_str,
            status="ok" if code == 0 else "failure",
            message="Command finished" if code == 0 else "Command failed",
            metadata={"exit_code": code, "duration_ms": duration_ms},
        )
        return ToolResult(
            status=status,
            tool="run_terminal",
            error=None if code == 0 else f"Exit code {code}",
            code="ok" if code == 0 else "failure",
            data={
                "command": command_str,
                "cwd": str(cwd),
                "exit_code": code,
                "stdout": stdout,
                "stderr": stderr,
                "duration_ms": duration_ms,
                "truncated": len(stdout_b) > self.output_limit or len(stderr_b) > self.output_limit,
            },
        )


def PathName(value: str) -> str:
    base = value.replace("\\", "/").split("/")[-1]
    return base.lower()


def _is_allowed(executable: str) -> bool:
    name = executable.lower()
    if name.endswith(".exe") or name.endswith(".cmd") or name.endswith(".bat"):
        name = name.rsplit(".", 1)[0]
    return any(name == p or name.startswith(p) for p in _ALLOWED_PREFIXES)


def _clip(text: str, limit: int) -> str:
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= limit:
        return text
    return encoded[:limit].decode("utf-8", errors="replace") + "\n…[truncated]"


def _short(command: str, n: int = 80) -> str:
    return command if len(command) <= n else command[: n - 1] + "…"


def _terminate_process(proc: asyncio.subprocess.Process | None) -> None:
    if proc is None or proc.returncode is not None:
        return
    try:
        if sys.platform == "win32":
            proc.terminate()
        else:
            proc.send_signal(signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.kill()
    except ProcessLookupError:
        return
