"""
Final E2E test for autonomous agent behavior.
Tests:
- No 10-minute timeout (can run long tasks)
- No terminal allowlist (all commands allowed at terminal level)
- create_directory tool works
- delete_directory works
- No approval blocking for workspace operations
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.config.settings import Settings


@pytest.mark.asyncio
async def test_timeout_extended_to_one_hour() -> None:
    """
    Verify that the task timeout is set to 3600 seconds (1 hour).
    This removes the artificial 10-minute timeout that was blocking long tasks.
    """
    settings = Settings()
    assert settings.agent_task_timeout_seconds == 3600.0, (
        f"Expected 3600s (1 hour) timeout, got {settings.agent_task_timeout_seconds}s"
    )


@pytest.mark.asyncio
async def test_terminal_allowlist_removed() -> None:
    """
    Verify that terminal commands are no longer restricted by an allowlist.
    The terminal module should not check _is_allowed() anymore.
    Commands are now evaluated only by the permission policy.
    """
    from app.tools.terminal import TerminalSession
    from app.permissions.sandbox import PathSandbox
    from app.events.bus import EventBus
    from app.tools.base import ToolContext
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        sandbox = PathSandbox(Path(tmpdir))
        term = TerminalSession(sandbox, EventBus(), default_timeout=5, output_limit=1000)
        ctx = ToolContext(workspace_root=tmpdir, task_id="t")
        
        # Previously "echo" would fail with "not in allowed set"
        # Now it should either succeed (if echo exists) or fail with UNAVAILABLE (not found)
        # but NOT with PERMISSION_DENIED from allowlist
        result = await term.run({"command": "echo test"}, ctx)
        
        # Should NOT be PERMISSION_DENIED due to allowlist
        assert result.status != "permission_denied", (
            "Terminal still has allowlist restriction - command was blocked"
        )


@pytest.mark.asyncio
async def test_create_directory_tool_available() -> None:
    """
    Verify that create_directory is available in the tool specs.
    """
    from app.tools.filesystem import FilesystemTools
    from app.permissions.sandbox import PathSandbox
    from app.events.bus import EventBus
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        sandbox = PathSandbox(Path(tmpdir))
        fs = FilesystemTools(sandbox, EventBus())
        
        # Check that create_directory is in specs
        spec_names = {spec.name for spec in fs.specs()}
        assert "create_directory" in spec_names, "create_directory tool not found in filesystem specs"


@pytest.mark.asyncio
async def test_delete_directory_tool_available() -> None:
    """
    Verify that delete_directory is available and properly classified.
    """
    from app.tools.filesystem import FilesystemTools
    from app.permissions.sandbox import PathSandbox
    from app.permissions.policy import PermissionPolicy, PermissionLevel
    from app.events.bus import EventBus
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        sandbox = PathSandbox(Path(tmpdir))
        fs = FilesystemTools(sandbox, EventBus())
        policy = PermissionPolicy(sandbox)
        
        # Check that delete_directory is in specs
        spec_names = {spec.name for spec in fs.specs()}
        assert "delete_directory" in spec_names, "delete_directory tool not found in filesystem specs"
        
        # Check that it's classified as GREEN (autonomous) for normal directories
        decision = policy.evaluate("delete_directory", {"path": "temp"})
        assert decision.level == PermissionLevel.GREEN, (
            f"delete_directory should be GREEN for workspace dirs, got {decision.level}"
        )
        assert decision.allowed, "delete_directory should be allowed for workspace directories"


@pytest.mark.asyncio
async def test_autonomous_filesystem_operations() -> None:
    """
    End-to-end test: create directory, create file, delete directory.
    All should work autonomously without approval blocking.
    """
    from app.tools.filesystem import FilesystemTools
    from app.permissions.sandbox import PathSandbox
    from app.permissions.policy import PermissionPolicy
    from app.events.bus import EventBus
    from app.tools.base import ToolContext
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        sandbox = PathSandbox(workspace)
        fs = FilesystemTools(sandbox, EventBus())
        policy = PermissionPolicy(sandbox)
        ctx = ToolContext(workspace_root=str(workspace), task_id="t")
        
        # 1. Create directory
        mkdir_decision = policy.evaluate("create_directory", {"path": "src/components"})
        assert mkdir_decision.allowed, "create_directory should be autonomous"
        mkdir_result = await fs.create_directory({"path": "src/components"}, ctx)
        assert mkdir_result.status == "success", f"create_directory failed: {mkdir_result.error}"
        assert (workspace / "src" / "components").is_dir()
        
        # 2. Create file
        write_decision = policy.evaluate("write_file", {"path": "src/components/app.py", "content": "x=1"})
        assert write_decision.allowed, "write_file should be autonomous for source files"
        write_result = await fs.write_file({"path": "src/components/app.py", "content": "x=1"}, ctx)
        assert write_result.status == "success", f"write_file failed: {write_result.error}"
        
        # 3. Delete directory
        rmdir_decision = policy.evaluate("delete_directory", {"path": "src"})
        assert rmdir_decision.allowed, "delete_directory should be autonomous"
        rmdir_result = await fs.delete_directory({"path": "src"}, ctx)
        assert rmdir_result.status == "success", f"delete_directory failed: {rmdir_result.error}"
        assert not (workspace / "src").exists()
