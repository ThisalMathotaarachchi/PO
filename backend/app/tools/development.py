"""Higher-level development operations with project-type detection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.events.bus import EventBus
from app.events.types import EventType
from app.tools.base import ToolContext, ToolResult, ToolSpec, ToolStatus
from app.tools.terminal import TerminalSession


def development_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="run_tests",
            description="Run the project's test suite. Auto-detects pytest or npm test.",
            parameters={"type": "object", "properties": {"command": {"type": "string"}}, "required": []},
        ),
        ToolSpec(
            name="run_build",
            description="Run the project's build. Auto-detects npm run build or similar.",
            parameters={"type": "object", "properties": {"command": {"type": "string"}}, "required": []},
        ),
        ToolSpec(
            name="run_linter",
            description="Run a linter if one is configured (ruff, eslint, etc.).",
            parameters={"type": "object", "properties": {"command": {"type": "string"}}, "required": []},
        ),
    ]


class DevelopmentTools:
    def __init__(self, terminal: TerminalSession, workspace: Path, bus: EventBus) -> None:
        self.terminal = terminal
        self.workspace = workspace
        self.bus = bus

    def specs(self) -> list[ToolSpec]:
        return development_specs()

    def detect_stack(self) -> dict[str, Any]:
        root = self.workspace
        files = {p.name.lower() for p in root.iterdir()} if root.exists() else set()
        python = any(n in files for n in ("pyproject.toml", "requirements.txt", "setup.py", "pytest.ini"))
        node = "package.json" in files
        typescript = "tsconfig.json" in files
        vite = any(n.startswith("vite.config") for n in files)
        return {
            "python": python,
            "node": node,
            "typescript": typescript,
            "vite": vite,
            "react": node and (typescript or vite),
        }

    def _test_command(self) -> str:
        stack = self.detect_stack()
        # Check if test suite actually exists
        if stack["python"]:
            # Check for pytest or tests directory
            has_tests = (
                (self.workspace / "tests").exists() or
                (self.workspace / "test").exists() or
                any(self.workspace.glob("test_*.py")) or
                any(self.workspace.glob("*_test.py"))
            )
            if has_tests:
                return f"{_python()} -m pytest -q"
            return ""  # No tests - don't force it
        if stack["node"]:
            # Check package.json for test script
            pkg_json = self.workspace / "package.json"
            if pkg_json.exists():
                try:
                    import json
                    data = json.loads(pkg_json.read_text(encoding="utf-8"))
                    if "test" in data.get("scripts", {}):
                        return "npm test -- --watchAll=false"
                except Exception:
                    pass
            return ""  # No test script
        return ""  # Unknown stack - no default test

    def _test_argv(self) -> list[str] | None:
        stack = self.detect_stack()
        if stack["python"] or not stack["node"]:
            return [_python(), "-m", "pytest", "-q"]
        return None

    def _build_command(self) -> str:
        stack = self.detect_stack()
        if stack["node"]:
            return "npm run build"
        if stack["python"]:
            return f"{_python()} -m compileall ."
        return f"{_python()} -m compileall ."

    def _lint_command(self) -> str:
        stack = self.detect_stack()
        if (self.workspace / "ruff.toml").exists() or stack["python"]:
            if (self.workspace / "ruff.toml").exists() or _has_ruff_config(self.workspace):
                return "ruff check ."
        if stack["node"]:
            return "npx eslint ."
        return "ruff check ."

    async def handle(self, name: str, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        override = str(arguments.get("command") or "").strip()
        if name == "run_tests":
            command = override or self._test_command()
            if not command:
                # No test suite detected
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    tool="run_tests",
                    data={"message": "No test suite detected. For static sites/simple projects, verify manually."},
                    code="no_tests"
                )
            payload = {"command": command}
            if not override:
                argv = self._test_argv()
                if argv:
                    payload["argv"] = argv
            await self.bus.emit(EventType.TEST_STARTED, task_id=context.task_id, command=command, message="Running tests…")
            result = await self.terminal.run(payload, context)
            result.tool = "run_tests"
            ok = result.status == ToolStatus.SUCCESS
            await self.bus.emit(
                EventType.TEST_COMPLETED,
                task_id=context.task_id,
                command=command,
                status="ok" if ok else "failure",
                message="✓ Tests passed." if ok else _fail_message(result),
            )
            return result
        if name == "run_build":
            command = override or self._build_command()
            result = await self.terminal.run({"command": command}, context)
            result.tool = "run_build"
            return result
        if name == "run_linter":
            command = override or self._lint_command()
            # Check if linter is available before running
            if "ruff" in command:
                check_result = await self.terminal.run({"command": "ruff --version"}, context)
                if check_result.status != ToolStatus.SUCCESS:
                    return ToolResult(
                        status=ToolStatus.UNAVAILABLE,
                        tool="run_linter",
                        error="ruff is not installed",
                        code="unavailable"
                    )
            result = await self.terminal.run({"command": command}, context)
            result.tool = "run_linter"
            return result
        return ToolResult(status=ToolStatus.INVALID_ARGUMENTS, tool=name, error="Unknown development tool", code="invalid_arguments")


def _python() -> str:
    import sys

    return sys.executable


def _has_ruff_config(root: Path) -> bool:
    pyproject = root / "pyproject.toml"
    if not pyproject.exists():
        return False
    try:
        return "[tool.ruff" in pyproject.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def _fail_message(result: ToolResult) -> str:
    stderr = str(result.data.get("stderr") or "")
    stdout = str(result.data.get("stdout") or "")
    blob = stdout + "\n" + stderr
    failed = 0
    for token in ("failed", "FAIL", "ERROR"):
        if token.lower() in blob.lower():
            failed += 1
    return "Tests failing. Fixing…" if failed else "Tests failed."
