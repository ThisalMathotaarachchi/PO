"""Filesystem tools constrained to the active workspace."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app.events.bus import EventBus
from app.events.types import EventType
from app.permissions.sandbox import PathResolutionError, PathSandbox
from app.tools.base import ToolContext, ToolResult, ToolSpec, ToolStatus

# Paths with these suffixes are files, never directories.
FILE_SUFFIXES = {
    ".html", ".htm", ".css", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".json", ".md", ".txt", ".py", ".pyi", ".toml", ".yml", ".yaml",
    ".xml", ".svg", ".csv", ".sql", ".sh", ".ps1", ".bat", ".ini", ".cfg",
    ".rs", ".go", ".java", ".kt", ".cs", ".vue", ".scss", ".less", ".map",
    ".lock", ".env",
}


def looks_like_file_path(path: str) -> bool:
    """True when the last path segment has a normal source/asset file suffix."""
    name = str(path or "").replace("\\", "/").rstrip("/").split("/")[-1]
    if not name or name in {".", ".."}:
        return False
    suffix = Path(name).suffix.lower()
    return suffix in FILE_SUFFIXES


def _specs() -> list[ToolSpec]:
    path_prop = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
    return [
        ToolSpec(name="list_directory", description="List files and directories in a workspace path.", parameters={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Directory path relative to workspace"}},
            "required": ["path"],
        }),
        ToolSpec(name="read_file", description="Read a text file. Use offset/limit for large files.", parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "offset": {"type": "integer", "description": "1-based start line"},
                "limit": {"type": "integer", "description": "Max lines to return"},
            },
            "required": ["path"],
        }),
        ToolSpec(
            name="write_file",
            description=(
                "Create or overwrite a FILE (not a folder). Use this for paths with extensions "
                "such as .html, .css, .js, .py, .md, .json, .ts, .tsx. Parent folders are created automatically. "
                "Do not use create_directory for these paths."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to workspace, including filename and extension"},
                    "content": {"type": "string", "description": "Full text contents of the file"},
                },
                "required": ["path", "content"],
            },
        ),
        ToolSpec(
            name="create_file",
            description=(
                "Create a new FILE that must not already exist. Same rules as write_file: this is for files "
                "with names like index.html or app.py, never for folders."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path including filename and extension"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        ),
        ToolSpec(name="delete_file", description="Delete a single file in the workspace. Use delete_directory for folders.", parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        }),
        ToolSpec(name="delete_directory", description="Delete a directory and ALL its contents recursively. Use this to delete folders.", parameters={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Directory path to delete recursively"}},
            "required": ["path"],
        }),
        ToolSpec(
            name="create_directory",
            description=(
                "Create a FOLDER only. Path must be a directory name without a file extension "
                "(for example src, assets, components). Never use this for files such as index.html, "
                "styles.css, script.js, README.md, app.py, or package.json — use write_file or create_file instead. "
                "write_file already creates missing parent folders."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path with no file extension. Not for .html/.css/.js/.py/.md/.json files.",
                        "pattern": "^(?!.*\\.(html|htm|css|js|mjs|cjs|ts|tsx|jsx|json|md|txt|py|pyi|toml|yml|yaml|xml|svg|csv|sql|sh|ps1|bat|ini|cfg|rs|go|java|kt|cs|vue|scss|less|map|lock|env)$).+$",
                    }
                },
                "required": ["path"],
            },
        ),
        ToolSpec(name="rename_file", description="Rename or move a file within the workspace.", parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}, "new_path": {"type": "string"}},
            "required": ["path", "new_path"],
        }),
        ToolSpec(name="file_exists", description="Check whether a path exists in the workspace.", parameters=path_prop),
    ]


class FilesystemTools:
    def __init__(
        self,
        sandbox: PathSandbox,
        bus: EventBus,
        *,
        read_limit_bytes: int = 100_000,
        ignore_directories: list[str] | None = None,
        snapshots: dict[str, str] | None = None,
    ) -> None:
        self.sandbox = sandbox
        self.bus = bus
        self.read_limit_bytes = read_limit_bytes
        self.ignore_directories = set(ignore_directories or [])
        self.snapshots = snapshots

    def specs(self) -> list[ToolSpec]:
        return _specs()

    async def handle(self, name: str, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        handlers = {
            "list_directory": self.list_directory,
            "read_file": self.read_file,
            "write_file": self.write_file,
            "create_file": self.create_file,
            "delete_file": self.delete_file,
            "delete_directory": self.delete_directory,
            "create_directory": self.create_directory,
            "rename_file": self.rename_file,
            "file_exists": self.file_exists,
        }
        handler = handlers.get(name)
        if not handler:
            return ToolResult(status=ToolStatus.INVALID_ARGUMENTS, tool=name, error="Unknown filesystem tool", code="invalid_arguments")
        try:
            return await handler(arguments, context)
        except PathResolutionError as exc:
            status = ToolStatus.PERMISSION_DENIED if exc.code == "permission_denied" else (
                ToolStatus.UNAVAILABLE if exc.code == "unavailable" else ToolStatus.INVALID_ARGUMENTS
            )
            return ToolResult(status=status, tool=name, error=str(exc), code=exc.code)

    async def list_directory(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        resolved = self.sandbox.resolve(str(arguments.get("path") or "."), must_exist=True)
        if not resolved.absolute.is_dir():
            return ToolResult(status=ToolStatus.INVALID_ARGUMENTS, tool="list_directory", error="Not a directory", code="invalid_arguments")
        entries: list[dict[str, Any]] = []
        with os.scandir(resolved.absolute) as it:
            for entry in it:
                if entry.name in self.ignore_directories:
                    continue
                entries.append({
                    "name": entry.name,
                    "path": (Path(resolved.relative) / entry.name).as_posix() if resolved.relative != "." else entry.name,
                    "is_dir": entry.is_dir(follow_symlinks=False),
                    "size": entry.stat(follow_symlinks=False).st_size if entry.is_file(follow_symlinks=False) else None,
                })
        entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
        return ToolResult(status=ToolStatus.SUCCESS, tool="list_directory", data={"entries": entries, "path": resolved.relative})

    async def read_file(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        resolved = self.sandbox.resolve(str(arguments.get("path")), must_exist=True)
        if resolved.absolute.is_dir():
            return ToolResult(status=ToolStatus.INVALID_ARGUMENTS, tool="read_file", error="Path is a directory", code="invalid_arguments")
        size = resolved.absolute.stat().st_size
        offset = int(arguments.get("offset") or 1)
        limit = arguments.get("limit")
        text = resolved.absolute.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        start = max(offset - 1, 0)
        truncated = False
        if limit is not None:
            end = start + int(limit)
            chosen = lines[start:end]
            truncated = end < len(lines) or start > 0
        else:
            encoded = text.encode("utf-8", errors="replace")
            if size > self.read_limit_bytes or len(encoded) > self.read_limit_bytes:
                # Return a prefix
                prefix = encoded[: self.read_limit_bytes].decode("utf-8", errors="replace")
                chosen = prefix.splitlines()
                truncated = True
            else:
                chosen = lines[start:]
        content = "\n".join(chosen)
        await self.bus.emit(
            EventType.FILE_READ,
            task_id=context.task_id,
            path=resolved.relative,
            message=f"Reading {resolved.relative}…",
        )
        return ToolResult(
            status=ToolStatus.SUCCESS,
            tool="read_file",
            data={
                "path": resolved.relative,
                "content": content,
                "truncated": truncated,
                "total_lines": len(lines),
                "size": size,
            },
        )

    async def write_file(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        return await self._write(arguments, context, create_only=False, tool="write_file")

    async def create_file(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        return await self._write(arguments, context, create_only=True, tool="create_file")

    async def _write(self, arguments: dict[str, Any], context: ToolContext, *, create_only: bool, tool: str) -> ToolResult:
        if "content" not in arguments:
            return ToolResult(status=ToolStatus.INVALID_ARGUMENTS, tool=tool, error="content is required", code="invalid_arguments")
        resolved = self.sandbox.resolve(str(arguments.get("path")))
        if resolved.exists and resolved.absolute.is_dir():
            return ToolResult(
                status=ToolStatus.FAILURE,
                tool=tool,
                error=(
                    f"'{resolved.relative}' is a directory, not a file. "
                    "Use write_file with a filename (for example styles.css) or delete the directory first."
                ),
                code="is_directory",
            )
        if create_only and resolved.exists:
            return ToolResult(status=ToolStatus.FAILURE, tool=tool, error="File already exists", code="failure")
        resolved.absolute.parent.mkdir(parents=True, exist_ok=True)
        content = arguments["content"]
        if not isinstance(content, str):
            content = str(content)
        if self.snapshots is not None and resolved.relative not in self.snapshots:
            if resolved.exists and resolved.absolute.is_file():
                try:
                    self.snapshots[resolved.relative] = resolved.absolute.read_text(
                        encoding="utf-8", errors="replace"
                    )
                except OSError:
                    self.snapshots[resolved.relative] = ""
            else:
                self.snapshots[resolved.relative] = ""
        resolved.absolute.write_text(content, encoding="utf-8", newline="\n")
        await self.bus.emit(
            EventType.FILE_CHANGED,
            task_id=context.task_id,
            path=resolved.relative,
            tool=tool,
            message=f"Editing {resolved.relative}…",
        )
        return ToolResult(status=ToolStatus.SUCCESS, tool=tool, data={"path": resolved.relative, "bytes": len(content.encode("utf-8"))})

    async def delete_file(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        resolved = self.sandbox.resolve(str(arguments.get("path")), must_exist=True)
        if resolved.absolute.is_dir():
            return ToolResult(status=ToolStatus.INVALID_ARGUMENTS, tool="delete_file", error="Refusing to delete a directory without approval path", code="invalid_arguments")
        resolved.absolute.unlink()
        await self.bus.emit(EventType.FILE_CHANGED, task_id=context.task_id, path=resolved.relative, tool="delete_file", message=f"Deleted {resolved.relative}")
        return ToolResult(status=ToolStatus.SUCCESS, tool="delete_file", data={"path": resolved.relative})

    async def delete_directory(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        """Delete a directory and all its contents (requires YELLOW approval via policy)."""
        import shutil
        resolved = self.sandbox.resolve(str(arguments.get("path")), must_exist=True)
        if not resolved.absolute.is_dir():
            return ToolResult(status=ToolStatus.INVALID_ARGUMENTS, tool="delete_directory", error="Path is not a directory", code="invalid_arguments")
        # Extra safety: refuse workspace root
        rel = resolved.relative.replace("\\", "/")
        if rel in {"", ".", "/"}:
            return ToolResult(status=ToolStatus.PERMISSION_DENIED, tool="delete_directory", error="Deleting the workspace root is blocked", code="destructive_blocked")
        shutil.rmtree(resolved.absolute)
        await self.bus.emit(EventType.FILE_CHANGED, task_id=context.task_id, path=resolved.relative, tool="delete_directory", message=f"Deleted directory {resolved.relative}")
        return ToolResult(status=ToolStatus.SUCCESS, tool="delete_directory", data={"path": resolved.relative})

    async def rename_file(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        src = self.sandbox.resolve(str(arguments.get("path")), must_exist=True)
        dest = self.sandbox.resolve(str(arguments.get("new_path")))
        dest.absolute.parent.mkdir(parents=True, exist_ok=True)
        src.absolute.replace(dest.absolute)
        await self.bus.emit(EventType.FILE_CHANGED, task_id=context.task_id, path=dest.relative, tool="rename_file", message=f"Renamed {src.relative}")
        return ToolResult(status=ToolStatus.SUCCESS, tool="rename_file", data={"path": src.relative, "new_path": dest.relative})

    async def file_exists(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        resolved = self.sandbox.resolve(str(arguments.get("path")))
        return ToolResult(
            status=ToolStatus.SUCCESS,
            tool="file_exists",
            data={"path": resolved.relative, "exists": resolved.exists, "is_dir": resolved.is_dir},
        )

    async def create_directory(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        raw_path = str(arguments.get("path") or "")
        if looks_like_file_path(raw_path):
            return ToolResult(
                status=ToolStatus.INVALID_ARGUMENTS,
                tool="create_directory",
                error=(
                    f"'{raw_path}' looks like a file, not a directory. "
                    "Use write_file or create_file to create files with extensions."
                ),
                code="path_is_file",
                data={
                    "suggested_tool": "write_file",
                    "suggested_arguments": {"path": raw_path, "content": ""},
                    "original_path": raw_path,
                },
            )
        resolved = self.sandbox.resolve(raw_path)
        if resolved.exists and resolved.is_dir:
            # Directory already exists - idempotent success
            return ToolResult(status=ToolStatus.SUCCESS, tool="create_directory", data={"path": resolved.relative, "already_exists": True})
        if resolved.exists:
            return ToolResult(status=ToolStatus.FAILURE, tool="create_directory", error="Path exists but is not a directory", code="failure")
        resolved.absolute.mkdir(parents=True, exist_ok=True)
        await self.bus.emit(
            EventType.FILE_CHANGED,
            task_id=context.task_id,
            path=resolved.relative,
            tool="create_directory",
            message=f"Created folder {resolved.relative}",
        )
        return ToolResult(status=ToolStatus.SUCCESS, tool="create_directory", data={"path": resolved.relative})
