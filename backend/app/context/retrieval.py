"""Task-driven retrieval: relevant files, not the whole repo."""

from __future__ import annotations

import re
from pathlib import Path

from app.context.indexing import ProjectIndex
from app.context.project import ProjectProfile, inspect_project
from app.events.bus import EventBus
from app.events.types import EventType
from app.memory.manager import MemoryManager

# Files that contain project-specific instructions for Po.
# Read in priority order; the first one found wins (unless both exist, then both are used).
_INSTRUCTION_CANDIDATES = [
    ".po/instructions.md",
    "AGENTS.md",
    ".po/AGENTS.md",
    "CLAUDE.md",      # honour Anthropic convention if present
]
_MAX_INSTRUCTION_BYTES = 8_000


def _read_project_instructions(workspace: Path) -> str | None:
    """Return the content of the first project-instruction file found, or None."""
    parts: list[str] = []
    for rel in _INSTRUCTION_CANDIDATES:
        candidate = workspace / rel
        try:
            if candidate.is_file():
                text = candidate.read_text(encoding="utf-8", errors="replace")[:_MAX_INSTRUCTION_BYTES]
                if text.strip():
                    parts.append(f"[{rel}]\n{text.strip()}")
        except OSError:
            continue
    return "\n\n".join(parts) if parts else None


class ContextEngine:
    def __init__(
        self,
        index: ProjectIndex,
        memory: MemoryManager,
        bus: EventBus,
        ignore_directories: list[str],
    ) -> None:
        self.index = index
        self.memory = memory
        self.bus = bus
        self.ignore = set(ignore_directories)

    async def gather(
        self,
        *,
        project_id: str,
        workspace: Path,
        prompt: str,
        task_id: str,
    ) -> tuple[ProjectProfile, list[str], str]:
        await self.bus.emit(EventType.CONTEXT_STARTED, task_id=task_id, message="Reading project…")
        profile = inspect_project(workspace, self.ignore)
        rows = await self.index.refresh(project_id, workspace)
        relevant = self.relevant_paths(prompt, rows, profile)
        memories = await self.memory.relevant_memories(project_id)
        memory_lines = [f"- [{m['kind']}] {m['content']}" for m in memories[:8]]

        blob: list[str] = []

        # Project instructions take precedence — prepend before everything else
        instructions = _read_project_instructions(workspace)
        if instructions:
            blob.append("Project instructions:")
            blob.append(instructions)
            blob.append("")   # blank line separator

        blob += [
            profile.as_prompt(),
            "Relevant files:",
            *([f"- {p}" for p in relevant] or ["- (none ranked yet)"]),
        ]
        if memory_lines:
            blob.append("Known project facts:")
            blob.extend(memory_lines)

        text = "\n".join(blob)
        await self.bus.emit(
            EventType.CONTEXT_COMPLETED,
            task_id=task_id,
            message="Project context ready",
            metadata={"files": relevant[:20], "languages": profile.languages},
        )
        return profile, relevant, text

    def relevant_paths(self, prompt: str, rows: list[dict], profile: ProjectProfile) -> list[str]:
        tokens = {t.lower() for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", prompt)}
        scored: list[tuple[int, str]] = []
        for row in rows:
            path = str(row["path"])
            lower = path.lower()
            score = 0
            for token in tokens:
                if token in lower:
                    score += 3
                symbols = row.get("symbols") or []
                if any(token == str(s).lower() for s in symbols):
                    score += 5
            if any(part in lower for part in ("test", "spec")):
                score += 1
            if profile.manifests and Path(path).name in profile.manifests:
                score += 4
            if Path(path).name.lower().startswith("readme"):
                score += 2
            if score:
                scored.append((score, path))
        scored.sort(key=lambda x: -x[0])
        if scored:
            return [p for _, p in scored[:25]]
        # fallback: manifests + tests + small source files
        preferred = list(profile.manifests) + list(profile.entry_points)
        for row in rows:
            name = Path(row["path"]).name
            if name in preferred or "test" in row["path"].lower():
                if row["path"] not in preferred:
                    preferred.append(row["path"])
        return preferred[:25]
