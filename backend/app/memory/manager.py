"""Structured project memory — summaries and facts, not raw transcripts."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from app.memory.database import Database, utcnow


class MemoryManager:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def list_projects(self) -> list[dict[str, Any]]:
        return await self.db.fetch_all("SELECT * FROM projects ORDER BY updated_at DESC")

    async def upsert_project(self, project_id: str, path: str, name: str, stack: str = "") -> None:
        existing = await self.db.fetch_one("SELECT id FROM projects WHERE id = ?", (project_id,))
        now = utcnow()
        if existing:
            await self.db.execute(
                "UPDATE projects SET path = ?, name = ?, stack = ?, updated_at = ? WHERE id = ?",
                (path, name, stack, now, project_id),
            )
        else:
            await self.db.execute(
                "INSERT INTO projects (id, path, name, stack, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (project_id, path, name, stack, now, now),
            )

    async def get_project_by_path(self, path: str) -> dict[str, Any] | None:
        return await self.db.fetch_one("SELECT * FROM projects WHERE path = ?", (path,))

    async def get_project(self, project_id: str) -> dict[str, Any] | None:
        return await self.db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))

    async def create_session(self, project_id: str) -> str:
        session_id = uuid4().hex
        await self.db.execute(
            "INSERT INTO sessions (id, project_id, created_at) VALUES (?, ?, ?)",
            (session_id, project_id, utcnow()),
        )
        return session_id

    async def create_task(
        self,
        *,
        task_id: str,
        project_id: str,
        session_id: str | None,
        prompt: str,
        status: str,
        model: str = "",
    ) -> None:
        now = utcnow()
        await self.db.execute(
            """INSERT INTO tasks (id, project_id, session_id, prompt, status, summary, model, error, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (task_id, project_id, session_id, prompt, status, "", model, "", now, now),
        )

    async def update_task(
        self,
        task_id: str,
        *,
        status: str | None = None,
        summary: str | None = None,
        model: str | None = None,
        error: str | None = None,
    ) -> None:
        row = await self.db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
        if not row:
            return
        await self.db.execute(
            """UPDATE tasks SET status = ?, summary = ?, model = ?, error = ?, updated_at = ? WHERE id = ?""",
            (
                status if status is not None else row["status"],
                summary if summary is not None else row["summary"],
                model if model is not None else row["model"],
                error if error is not None else row["error"],
                utcnow(),
                task_id,
            ),
        )

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        return await self.db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))

    async def add_step(self, task_id: str, seq: int, state: str, action: str, summary: str) -> None:
        await self.db.execute(
            "INSERT INTO task_steps (id, task_id, seq, state, action, summary, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (uuid4().hex, task_id, seq, state, action, summary, utcnow()),
        )

    async def add_memory(self, project_id: str, kind: str, content: str) -> str:
        memory_id = uuid4().hex
        await self.db.execute(
            "INSERT INTO memories (id, project_id, kind, content, created_at) VALUES (?, ?, ?, ?, ?)",
            (memory_id, project_id, kind, content, utcnow()),
        )
        return memory_id

    async def relevant_memories(self, project_id: str, limit: int = 12) -> list[dict[str, Any]]:
        return await self.db.fetch_all(
            "SELECT * FROM memories WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
            (project_id, limit),
        )

    async def record_tool_call(
        self,
        task_id: str,
        tool: str,
        arguments: dict[str, Any],
        status: str,
        result: dict[str, Any],
        duration_ms: int,
    ) -> None:
        await self.db.execute(
            """INSERT INTO tool_calls (id, task_id, tool, arguments, status, result, duration_ms, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                uuid4().hex,
                task_id,
                tool,
                json.dumps(arguments, default=str),
                status,
                json.dumps(result, default=str)[:20_000],
                duration_ms,
                utcnow(),
            ),
        )

    async def record_model_usage(
        self,
        task_id: str,
        model: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> None:
        await self.db.execute(
            """INSERT INTO model_usage (id, task_id, model, prompt_tokens, completion_tokens, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (uuid4().hex, task_id, model, prompt_tokens, completion_tokens, utcnow()),
        )

    async def replace_file_index(self, project_id: str, rows: list[dict[str, Any]]) -> None:
        await self.db.execute("DELETE FROM file_index WHERE project_id = ?", (project_id,))
        tuples = [
            (
                project_id,
                r["path"],
                r.get("extension"),
                r.get("language"),
                r.get("size"),
                r.get("mtime"),
                json.dumps(r.get("symbols") or []),
            )
            for r in rows
        ]
        if tuples:
            await self.db.execute_many(
                """INSERT INTO file_index (project_id, path, extension, language, size, mtime, symbols)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                tuples,
            )

    async def get_file_index(self, project_id: str) -> list[dict[str, Any]]:
        rows = await self.db.fetch_all("SELECT * FROM file_index WHERE project_id = ?", (project_id,))
        for row in rows:
            try:
                row["symbols"] = json.loads(row["symbols"] or "[]")
            except json.JSONDecodeError:
                row["symbols"] = []
        return rows
