from __future__ import annotations

from pathlib import Path

import pytest

from app.context.indexing import ProjectIndex
from app.context.project import inspect_project
from app.context.retrieval import ContextEngine
from app.events.bus import EventBus
from app.memory.database import Database
from app.memory.manager import MemoryManager


@pytest.mark.asyncio
async def test_project_detection_index_and_retrieval(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\nversion='0'\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "auth.py").write_text("def authenticate():\n    return True\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_auth.py").write_text("def test_authenticate():\n    pass\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    profile = inspect_project(tmp_path)
    assert "python" in profile.languages
    assert "pyproject.toml" in profile.manifests

    db = Database(tmp_path / "db.sqlite")
    await db.initialize()
    memory = MemoryManager(db)
    await memory.upsert_project("p1", str(tmp_path), "demo", "python")
    index = ProjectIndex(memory, [".git", "node_modules"], 1_000_000)
    rows = await index.refresh("p1", tmp_path)
    assert any(r["path"].endswith("auth.py") for r in rows)
    again = await index.refresh("p1", tmp_path)
    assert len(again) == len(rows)

    engine = ContextEngine(index, memory, EventBus(), [".git"])
    _profile, relevant, text = await engine.gather(
        project_id="p1", workspace=tmp_path, prompt="fix authentication", task_id="t"
    )
    assert any("auth" in p for p in relevant)
    assert "Project:" in text
