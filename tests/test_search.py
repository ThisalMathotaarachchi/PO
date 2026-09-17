from __future__ import annotations

from pathlib import Path

import pytest

from app.events.bus import EventBus
from app.permissions.sandbox import PathSandbox
from app.tools.base import ToolContext
from app.tools.search import SearchTools


@pytest.mark.asyncio
async def test_search_ignores_vendor_and_finds_code(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "auth.py").write_text("def login():\n    return True\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "secret.py").write_text("def login():\n    pass\n", encoding="utf-8")
    search = SearchTools(PathSandbox(tmp_path), EventBus(), ignore_directories=["node_modules", ".git"])
    ctx = ToolContext(workspace_root=str(tmp_path), task_id="t")
    files = await search.handle("search_files", {"query": "auth.py"}, ctx)
    assert "src/auth.py" in files.data["matches"]
    assert not any("node_modules" in m for m in files.data["matches"])
    code = await search.handle("search_code", {"query": "def login"}, ctx)
    assert any(m["path"].endswith("auth.py") for m in code.data["matches"])
    assert not any("node_modules" in m["path"] for m in code.data["matches"])
    symbols = await search.handle("find_symbol", {"name": "login"}, ctx)
    assert symbols.data["matches"]
    refs = await search.handle("find_references", {"name": "login"}, ctx)
    assert refs.data["matches"]
