"""
Lightweight project-level hook system.

Hooks are JSON records stored in the SQLite `memories` table with kind='hook'.
Each hook has a trigger event type and an action (shell command or agent
instruction). They are executed non-critically — a failing hook never aborts
the operation that triggered it.

Hook record schema (stored in memories.content as JSON):
{
    "id":       "unique-string",
    "name":     "Human-readable label",
    "trigger":  "TASK_COMPLETED" | "FILE_CHANGED" | "TASK_STARTED" | ...,
    "matcher":  "optional regex matched against event.path or event.tool",
    "action": {
        "type":    "command",
        "command": "npm run lint"
    }
}

Only "command" action type is implemented in this first pass.
The architecture is ready for "agent" action type (inject instruction).

Security: command actions run through the existing TerminalSession.run()
which enforces the allowed-command allowlist and workspace sandbox.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from app.events.types import AgentEvent, EventType
from app.tools.base import ToolContext, ToolStatus

if TYPE_CHECKING:
    from app.memory.manager import MemoryManager
    from app.tools.registry import ToolRegistry

logger = logging.getLogger("po.hooks")


class HookManager:
    """Subscribes to the event bus and executes matching hooks."""

    def __init__(self, memory: "MemoryManager", workspace_path: str) -> None:
        self.memory = memory
        self.workspace_path = workspace_path
        self._hooks: list[dict[str, Any]] = []
        self._tools: "ToolRegistry | None" = None

    def set_tools(self, tools: "ToolRegistry") -> None:
        self._tools = tools

    async def load(self, project_id: str) -> None:
        """Load hooks for a project from the database."""
        rows = await self.memory.db.fetch_all(
            "SELECT content FROM memories WHERE project_id = ? AND kind = ? ORDER BY id",
            (project_id, "hook"),
        )
        loaded: list[dict[str, Any]] = []
        for row in rows:
            try:
                h = json.loads(row["content"])
                if isinstance(h, dict) and h.get("trigger") and h.get("action"):
                    loaded.append(h)
            except (json.JSONDecodeError, KeyError):
                continue
        self._hooks = loaded
        logger.debug("hooks loaded: %d for project %s", len(loaded), project_id)

    async def handle_event(self, event: AgentEvent) -> None:
        """Called by the event bus subscriber. Runs matching hooks."""
        if not self._hooks:
            return
        for hook in self._hooks:
            if hook.get("trigger") != event.type:
                continue
            matcher = hook.get("matcher")
            if matcher:
                target = event.path or event.tool or event.message or ""
                try:
                    if not re.search(matcher, target):
                        continue
                except re.error:
                    continue
            await self._execute(hook, event)

    async def _execute(self, hook: dict[str, Any], event: AgentEvent) -> None:
        action = hook.get("action", {})
        atype = action.get("type")
        if atype == "command":
            await self._run_command(hook, action, event)
        else:
            logger.debug("unknown hook action type: %s", atype)

    async def _run_command(
        self,
        hook: dict[str, Any],
        action: dict[str, Any],
        event: AgentEvent,
    ) -> None:
        command = str(action.get("command") or "").strip()
        if not command or not self._tools:
            return
        ctx = ToolContext(workspace_root=self.workspace_path, task_id=f"hook:{hook.get('id','?')}")
        logger.info("running hook command: %s (trigger: %s)", command, event.type)
        try:
            result = await self._tools.terminal.run({"command": command}, ctx)
            if result.status != ToolStatus.SUCCESS:
                logger.warning(
                    "hook command failed: %s — %s",
                    command,
                    result.error or result.status,
                )
        except Exception as exc:
            logger.warning("hook command exception: %s", exc)


# ── CRUD helpers (used by workspace_io endpoints) ─────────────────────────────

async def list_hooks(memory: "MemoryManager", project_id: str) -> list[dict[str, Any]]:
    rows = await memory.db.fetch_all(
        "SELECT content FROM memories WHERE project_id = ? AND kind = ?",
        (project_id, "hook"),
    )
    hooks: list[dict[str, Any]] = []
    for row in rows:
        try:
            h = json.loads(row["content"])
            hooks.append(h)
        except json.JSONDecodeError:
            continue
    return hooks


async def save_hook(memory: "MemoryManager", project_id: str, hook: dict[str, Any]) -> None:
    import uuid
    if "id" not in hook:
        hook["id"] = uuid.uuid4().hex[:10]
    content = json.dumps(hook)
    # Upsert by hook id stored in the content (check if already exists)
    rows = await memory.db.fetch_all(
        "SELECT id, content FROM memories WHERE project_id = ? AND kind = ?",
        (project_id, "hook"),
    )
    for row in rows:
        try:
            existing = json.loads(row["content"])
            if existing.get("id") == hook["id"]:
                await memory.db.execute(
                    "UPDATE memories SET content = ? WHERE id = ?",
                    (content, row["id"]),
                )
                return
        except (json.JSONDecodeError, KeyError):
            continue
    await memory.add_memory(project_id, "hook", content)


async def delete_hook(memory: "MemoryManager", project_id: str, hook_id: str) -> bool:
    rows = await memory.db.fetch_all(
        "SELECT id, content FROM memories WHERE project_id = ? AND kind = ?",
        (project_id, "hook"),
    )
    for row in rows:
        try:
            existing = json.loads(row["content"])
            if existing.get("id") == hook_id:
                await memory.db.execute("DELETE FROM memories WHERE id = ?", (row["id"],))
                return True
        except (json.JSONDecodeError, KeyError):
            continue
    return False
