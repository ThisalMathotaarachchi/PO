"""Project search without dumping the whole repository."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from app.events.bus import EventBus
from app.events.types import EventType
from app.permissions.sandbox import PathSandbox
from app.tools.base import ToolContext, ToolResult, ToolSpec, ToolStatus

_TEXT_EXT = {
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".json", ".md", ".txt", ".toml",
    ".yml", ".yaml", ".css", ".html", ".rs", ".go", ".java", ".cs", ".sql",
    ".ini", ".cfg", ".xml", ".sh", ".ps1", ".bat", ".vue", ".c", ".h", ".cpp",
}


def search_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="search_files",
            description="Find files by glob-like name pattern (substring or wildcard).",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "path": {"type": "string"},
                },
                "required": ["query"],
            },
        ),
        ToolSpec(
            name="search_code",
            description="Search file contents for a regex or substring.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "path": {"type": "string"},
                    "regex": {"type": "boolean"},
                    "max_results": {"type": "integer"},
                },
                "required": ["query"],
            },
        ),
        ToolSpec(
            name="find_symbol",
            description="Find likely symbol definitions (functions, classes, types).",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        ),
        ToolSpec(
            name="find_references",
            description="Find references to a symbol name in the workspace.",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        ),
    ]


class SearchTools:
    def __init__(
        self,
        sandbox: PathSandbox,
        bus: EventBus,
        *,
        ignore_directories: list[str],
        max_results: int = 50,
        max_file_bytes: int = 1_048_576,
    ) -> None:
        self.sandbox = sandbox
        self.bus = bus
        self.ignore_directories = set(ignore_directories)
        self.max_results = max_results
        self.max_file_bytes = max_file_bytes

    def specs(self) -> list[ToolSpec]:
        return search_specs()

    def iter_files(self, root: Path) -> list[Path]:
        files: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in self.ignore_directories]
            for name in filenames:
                files.append(Path(dirpath) / name)
        return files

    async def handle(self, name: str, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        await self.bus.emit(EventType.SEARCH_STARTED, task_id=context.task_id, tool=name, message="Searching…")
        try:
            if name == "search_files":
                result = await self.search_files(arguments)
            elif name == "search_code":
                result = await self.search_code(arguments)
            elif name == "find_symbol":
                result = await self.find_symbol(arguments)
            elif name == "find_references":
                result = await self.find_references(arguments)
            else:
                return ToolResult(status=ToolStatus.INVALID_ARGUMENTS, tool=name, error="Unknown search tool", code="invalid_arguments")
        finally:
            await self.bus.emit(EventType.SEARCH_COMPLETED, task_id=context.task_id, tool=name, message="Search complete")
        return result

    def _root(self, arguments: dict[str, Any]) -> Path:
        path = arguments.get("path") or "."
        return self.sandbox.resolve(str(path), must_exist=True).absolute

    async def search_files(self, arguments: dict[str, Any]) -> ToolResult:
        query = str(arguments.get("query") or "").lower()
        if not query:
            return ToolResult(status=ToolStatus.INVALID_ARGUMENTS, tool="search_files", error="query is required", code="invalid_arguments")
        pattern = query.replace("\\", "/").replace("**", "*")
        root = self._root(arguments)
        matches: list[str] = []
        for file in self.iter_files(root):
            rel = file.resolve().relative_to(self.sandbox.workspace).as_posix()
            name = file.name.lower()
            hay = rel.lower()
            if query in hay or _wildcard_match(pattern, rel.lower()) or query in name:
                matches.append(rel)
            if len(matches) >= self.max_results:
                break
        return ToolResult(status=ToolStatus.SUCCESS, tool="search_files", data={"matches": matches})

    async def search_code(self, arguments: dict[str, Any]) -> ToolResult:
        query = str(arguments.get("query") or "")
        if not query:
            return ToolResult(status=ToolStatus.INVALID_ARGUMENTS, tool="search_code", error="query is required", code="invalid_arguments")
        use_regex = bool(arguments.get("regex"))
        max_results = int(arguments.get("max_results") or self.max_results)
        try:
            compiled = re.compile(query) if use_regex else None
        except re.error as exc:
            return ToolResult(status=ToolStatus.INVALID_ARGUMENTS, tool="search_code", error=f"Invalid regex: {exc}", code="invalid_arguments")
        root = self._root(arguments)
        hits: list[dict[str, Any]] = []
        for file in self.iter_files(root):
            if file.suffix.lower() not in _TEXT_EXT and file.suffix:
                continue
            try:
                if file.stat().st_size > self.max_file_bytes:
                    continue
                text = file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = file.resolve().relative_to(self.sandbox.workspace).as_posix()
            for i, line in enumerate(text.splitlines(), start=1):
                found = compiled.search(line) is not None if compiled else query in line
                if found:
                    hits.append({"path": rel, "line": i, "text": line.strip()[:300]})
                    if len(hits) >= max_results:
                        return ToolResult(status=ToolStatus.SUCCESS, tool="search_code", data={"matches": hits, "truncated": True})
        return ToolResult(status=ToolStatus.SUCCESS, tool="search_code", data={"matches": hits, "truncated": False})

    async def find_symbol(self, arguments: dict[str, Any]) -> ToolResult:
        name = str(arguments.get("name") or "")
        if not name:
            return ToolResult(status=ToolStatus.INVALID_ARGUMENTS, tool="find_symbol", error="name is required", code="invalid_arguments")
        pattern = re.compile(
            rf"^\s*(?:(?:export|public|async|static)\s+)*(?:def|class|function|const|let|var|interface|type|enum)\s+{re.escape(name)}\b"
        )
        root = self.sandbox.workspace
        hits: list[dict[str, Any]] = []
        for file in self.iter_files(root):
            if file.suffix.lower() not in _TEXT_EXT:
                continue
            try:
                text = file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = file.resolve().relative_to(self.sandbox.workspace).as_posix()
            for i, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line):
                    hits.append({"path": rel, "line": i, "text": line.strip()[:300]})
                    if len(hits) >= self.max_results:
                        break
        return ToolResult(status=ToolStatus.SUCCESS, tool="find_symbol", data={"matches": hits})

    async def find_references(self, arguments: dict[str, Any]) -> ToolResult:
        name = str(arguments.get("name") or "")
        arguments = {**arguments, "query": rf"\b{re.escape(name)}\b", "regex": True}
        result = await self.search_code(arguments)
        result.tool = "find_references"
        return result


def _wildcard_match(pattern: str, value: str) -> bool:
    if "*" not in pattern and "?" not in pattern:
        return False
    regex = re.escape(pattern).replace(r"\*", ".*").replace(r"\?", ".")
    return re.search(regex, value) is not None
