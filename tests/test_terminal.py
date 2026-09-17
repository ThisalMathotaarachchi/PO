from __future__ import annotations

import sys

import pytest

from app.events.bus import EventBus
from app.permissions.sandbox import PathSandbox
from app.tools.base import ToolContext, ToolStatus
from app.tools.terminal import TerminalSession


@pytest.mark.asyncio
async def test_terminal_success_and_cwd(tmp_path) -> None:
    (tmp_path / "marker.txt").write_text("ok", encoding="utf-8")
    term = TerminalSession(PathSandbox(tmp_path), EventBus(), default_timeout=15, output_limit=4000)
    ctx = ToolContext(workspace_root=str(tmp_path), task_id="t")
    result = await term.run(
        {"command": "python -c cwd", "argv": [sys.executable, "-c", "import os; print(os.getcwd())"]},
        ctx,
    )
    assert result.status == ToolStatus.SUCCESS
    stdout = result.data["stdout"]
    assert str(tmp_path.resolve()) in stdout or tmp_path.name in stdout
    assert result.data["exit_code"] == 0


@pytest.mark.asyncio
async def test_terminal_failure(tmp_path) -> None:
    term = TerminalSession(PathSandbox(tmp_path), EventBus(), default_timeout=15, output_limit=4000)
    ctx = ToolContext(workspace_root=str(tmp_path), task_id="t")
    result = await term.run({"command": "python exit", "argv": [sys.executable, "-c", "import sys; sys.exit(7)"]}, ctx)
    assert result.status == ToolStatus.FAILURE
    assert result.data["exit_code"] == 7


@pytest.mark.asyncio
async def test_terminal_timeout(tmp_path) -> None:
    term = TerminalSession(PathSandbox(tmp_path), EventBus(), default_timeout=0.3, output_limit=4000)
    ctx = ToolContext(workspace_root=str(tmp_path), task_id="t")
    result = await term.run(
        {
            "command": "python sleep",
            "argv": [sys.executable, "-c", "import time; time.sleep(10)"],
            "timeout": 0.4,
        },
        ctx,
    )
    assert result.status == ToolStatus.TIMEOUT


@pytest.mark.asyncio
async def test_terminal_output_limit(tmp_path) -> None:
    term = TerminalSession(PathSandbox(tmp_path), EventBus(), default_timeout=15, output_limit=200)
    ctx = ToolContext(workspace_root=str(tmp_path), task_id="t")
    result = await term.run({"command": "python print", "argv": [sys.executable, "-c", "print('x'*5000)"]}, ctx)
    assert result.status == ToolStatus.SUCCESS
    assert result.data["truncated"] is True
    assert len(result.data["stdout"].encode("utf-8")) <= 400


@pytest.mark.asyncio
async def test_disallowed_command(tmp_path) -> None:
    """Terminal allowlist removed - all commands now allowed at terminal level.
    Destructive commands are blocked by permission policy, not terminal allowlist."""
    term = TerminalSession(PathSandbox(tmp_path), EventBus(), default_timeout=5, output_limit=1000)
    ctx = ToolContext(workspace_root=str(tmp_path), task_id="t")
    # format is not a real command in most environments, so expect UNAVAILABLE
    result = await term.run({"command": "format C:"}, ctx)
    # Terminal no longer has allowlist - command would fail as UNAVAILABLE (not found)
    # or be blocked by policy layer (not terminal layer)
    assert result.status in {ToolStatus.UNAVAILABLE, ToolStatus.FAILURE}
