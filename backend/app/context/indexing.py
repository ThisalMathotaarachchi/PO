"""Lightweight file metadata index (no vector database)."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from app.memory.manager import MemoryManager

_SYMBOL_RE = re.compile(
    r"^\s*(?:(?:export|public|async|static)\s+)*(?:def|class|function|interface|type|enum)\s+([A-Za-z_][\w]*)",
    re.MULTILINE,
)

_LANG = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".cs": "csharp",
    ".md": "markdown",
    ".json": "json",
    ".toml": "toml",
    ".yml": "yaml",
    ".yaml": "yaml",
}


class ProjectIndex:
    def __init__(self, memory: MemoryManager, ignore_directories: list[str], max_file_bytes: int) -> None:
        self.memory = memory
        self.ignore = set(ignore_directories)
        self.max_file_bytes = max_file_bytes

    async def refresh(self, project_id: str, root: Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        root = root.resolve()
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in self.ignore]
            for name in filenames:
                path = Path(dirpath) / name
                try:
                    st = path.stat()
                except OSError:
                    continue
                rel = path.relative_to(root).as_posix()
                suffix = path.suffix.lower()
                symbols: list[str] = []
                if st.st_size <= self.max_file_bytes and suffix in _LANG:
                    try:
                        text = path.read_text(encoding="utf-8", errors="replace")
                        symbols = _SYMBOL_RE.findall(text)[:40]
                    except OSError:
                        symbols = []
                rows.append(
                    {
                        "path": rel,
                        "extension": suffix,
                        "language": _LANG.get(suffix, ""),
                        "size": st.st_size,
                        "mtime": st.st_mtime,
                        "symbols": symbols,
                    }
                )
        await self.memory.replace_file_index(project_id, rows)
        return rows

    async def get(self, project_id: str) -> list[dict[str, Any]]:
        return await self.memory.get_file_index(project_id)
