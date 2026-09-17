from __future__ import annotations

from pathlib import Path

import pytest

from app.permissions.sandbox import PathResolutionError, PathSandbox
from app.tools.base import ToolContext
from app.tools.filesystem import FilesystemTools
from app.events.bus import EventBus


@pytest.fixture
def fs(tmp_path: Path) -> tuple[FilesystemTools, Path]:
    sandbox = PathSandbox(tmp_path)
    tools = FilesystemTools(sandbox, EventBus(), ignore_directories=[".git", "node_modules"])
    return tools, tmp_path


@pytest.fixture
def ctx() -> ToolContext:
    return ToolContext(workspace_root=".", task_id="t1")


@pytest.mark.asyncio
async def test_write_read_create_rename_delete(fs, ctx) -> None:
    tools, root = fs
    created = await tools.create_file({"path": "src/app.py", "content": "print(1)\n"}, ctx)
    assert created.status == "success"
    assert (root / "src" / "app.py").read_text(encoding="utf-8") == "print(1)\n"
    exists = await tools.file_exists({"path": "src/app.py"}, ctx)
    assert exists.data["exists"] is True
    listed = await tools.list_directory({"path": "src"}, ctx)
    assert any(e["name"] == "app.py" for e in listed.data["entries"])
    written = await tools.write_file({"path": "src/app.py", "content": "print(2)\n"}, ctx)
    assert written.status == "success"
    read = await tools.read_file({"path": "src/app.py"}, ctx)
    assert "print(2)" in read.data["content"]
    renamed = await tools.rename_file({"path": "src/app.py", "new_path": "src/main.py"}, ctx)
    assert renamed.status == "success"
    deleted = await tools.delete_file({"path": "src/main.py"}, ctx)
    assert deleted.status == "success"
    assert not (root / "src" / "main.py").exists()


@pytest.mark.asyncio
async def test_create_file_fails_if_exists(fs, ctx) -> None:
    tools, _ = fs
    await tools.create_file({"path": "a.txt", "content": "x"}, ctx)
    again = await tools.create_file({"path": "a.txt", "content": "y"}, ctx)
    assert again.status == "failure"


@pytest.mark.asyncio
async def test_traversal_blocked(fs, ctx) -> None:
    tools, _ = fs
    result = await tools.handle("read_file", {"path": "../secret.txt"}, ctx)
    assert result.status.value in {"permission_denied", "unavailable"}
    assert result.code == "permission_denied"


@pytest.mark.asyncio
async def test_absolute_escape_blocked(fs, ctx, tmp_path: Path) -> None:
    tools, _ = fs
    outside = Path.home() / "po_should_not_read.txt"
    result = await tools.handle("read_file", {"path": str(outside)}, ctx)
    assert result.status.value == "permission_denied"


@pytest.mark.asyncio
async def test_partial_read_large_file(fs, ctx) -> None:
    tools, root = fs
    tools.read_limit_bytes = 50
    (root / "big.txt").write_text("x" * 400, encoding="utf-8")
    result = await tools.read_file({"path": "big.txt"}, ctx)
    assert result.data["truncated"] is True


@pytest.mark.asyncio
async def test_create_directory(fs, ctx) -> None:
    """Test that create_directory tool works correctly."""
    tools, root = fs
    # Create a nested directory structure
    result = await tools.create_directory({"path": "src/components/forms"}, ctx)
    assert result.status == "success"
    assert (root / "src" / "components" / "forms").is_dir()
    # Verify the path exists
    exists = await tools.file_exists({"path": "src/components/forms"}, ctx)
    assert exists.data["exists"] is True
    assert exists.data["is_dir"] is True
    # Try to create an existing directory - should succeed (idempotent)
    result2 = await tools.create_directory({"path": "src/components/forms"}, ctx)
    assert result2.status == "success"
    assert result2.data.get("already_exists") is True


@pytest.mark.asyncio
async def test_delete_directory(fs, ctx) -> None:
    """Test that delete_directory tool works correctly."""
    tools, root = fs
    # Create a directory with files
    (root / "temp" / "subdir").mkdir(parents=True)
    (root / "temp" / "file1.txt").write_text("content1")
    (root / "temp" / "subdir" / "file2.txt").write_text("content2")
    # Delete the directory
    result = await tools.delete_directory({"path": "temp"}, ctx)
    assert result.status == "success"
    assert not (root / "temp").exists()
    # Verify it's gone
    exists = await tools.file_exists({"path": "temp"}, ctx)
    assert exists.data["exists"] is False
