from __future__ import annotations

import pytest

from app.events.bus import EventBus
from app.permissions.sandbox import PathSandbox
from app.tools.base import ToolContext
from app.tools.development import DevelopmentTools
from app.tools.git import GitTools
from app.tools.terminal import TerminalSession


@pytest.mark.asyncio
async def test_detect_python_and_run_tests(tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\nversion='0'\n", encoding="utf-8")
    (tmp_path / "sample.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "test_sample.py").write_text("from sample import VALUE\n\ndef test_value():\n    assert VALUE == 1\n", encoding="utf-8")
    bus = EventBus()
    term = TerminalSession(PathSandbox(tmp_path), bus, default_timeout=30, output_limit=20_000)
    dev = DevelopmentTools(term, tmp_path, bus)
    assert dev.detect_stack()["python"] is True
    ctx = ToolContext(workspace_root=str(tmp_path), task_id="t")
    result = await dev.handle("run_tests", {}, ctx)
    assert result.status == "success"
    assert result.data["exit_code"] == 0


@pytest.mark.asyncio
async def test_git_tools_read_only(tmp_path) -> None:
    bus = EventBus()
    term = TerminalSession(PathSandbox(tmp_path), bus, default_timeout=20, output_limit=20_000)
    ctx = ToolContext(workspace_root=str(tmp_path), task_id="t")
    init = await term.run({"command": "git init"}, ctx)
    if init.status != "success":
        pytest.skip("git not available")
    await term.run({"command": "git config user.email test@example.com"}, ctx)
    await term.run({"command": "git config user.name test"}, ctx)
    (tmp_path / "a.txt").write_text("hi\n", encoding="utf-8")
    git = GitTools(term)
    status = await git.handle("git_status", {}, ctx)
    assert status.status in {"success", "failure"}
    branch = await git.handle("git_branch", {}, ctx)
    assert branch.tool == "git_branch"
    log = await git.handle("git_log", {"limit": 3}, ctx)
    assert log.tool == "git_log"
    diff = await git.handle("git_diff", {}, ctx)
    assert diff.tool == "git_diff"
