from __future__ import annotations

from pathlib import Path

import pytest

from app.memory.database import Database
from app.memory.manager import MemoryManager


@pytest.mark.asyncio
async def test_database_init_and_persistence(tmp_path: Path) -> None:
    path = tmp_path / "po.db"
    db = Database(path)
    await db.initialize()
    await db.initialize()
    memory = MemoryManager(db)
    await memory.upsert_project("p1", str(tmp_path), "demo")
    await memory.create_task(task_id="t1", project_id="p1", session_id=None, prompt="do work", status="IDLE")
    await memory.update_task("t1", status="COMPLETED", summary="Done.")
    await memory.add_step("t1", 1, "EXECUTING", "read_file", "Reading a.py…")
    await memory.add_memory("p1", "stack", "python")
    await memory.record_tool_call("t1", "read_file", {"path": "a.py"}, "success", {"ok": True}, 12)
    await db.insert_event("t1", "TASK_STARTED", {"hello": True})
    task = await memory.get_task("t1")
    assert task["status"] == "COMPLETED"
    mems = await memory.relevant_memories("p1")
    assert mems
    events = await db.fetch_all("SELECT * FROM events WHERE task_id = ?", ("t1",))
    assert events
    db2 = Database(path)
    await db2.initialize()
    memory2 = MemoryManager(db2)
    again = await memory2.get_task("t1")
    assert again["summary"] == "Done."
