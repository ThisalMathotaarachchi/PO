"""UI-facing workspace file, search, terminal, and change APIs. Reuse sandbox + tools."""

from __future__ import annotations

import difflib
from typing import Any

from fastapi import APIRouter, HTTPException, Request
import asyncio
from pydantic import BaseModel

from app.container import AppContainer
from app.tools.base import ToolContext, ToolResult, ToolStatus
from app.workspace.manager import WorkspaceError

files_router = APIRouter()


class FileBody(BaseModel):
    path: str
    content: str = ""


class RenameBody(BaseModel):
    path: str
    new_path: str


class PathBody(BaseModel):
    path: str


class TerminalBody(BaseModel):
    command: str
    timeout: float | None = None


def _c(request: Request) -> AppContainer:
    return request.app.state.container


def _tools(request: Request):
    c = _c(request)
    try:
        ws = c.workspace.require_active()
    except WorkspaceError as exc:
        raise HTTPException(400, str(exc)) from exc
    return c.tools_for(ws), ws, c


def _ctx(ws) -> ToolContext:
    return ToolContext(workspace_root=ws.path, task_id="ui")


async def _run_tool(request: Request, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    tools, ws, _cont = _tools(request)
    validated = tools.validate_call({"tool": tool, "arguments": arguments})
    if isinstance(validated, ToolResult):
        _raise(validated)
    result = await tools.execute(validated, _ctx(ws))
    return _payload(result)


def _payload(result: ToolResult) -> dict[str, Any]:
    if result.status != ToolStatus.SUCCESS:
        _raise(result)
    return result.as_model_content()


def _raise(result: ToolResult) -> None:
    code = 400
    if result.status == ToolStatus.PERMISSION_DENIED:
        code = 403
    elif result.status == ToolStatus.UNAVAILABLE:
        code = 404
    elif result.status == ToolStatus.TIMEOUT:
        code = 504
    elif result.status == ToolStatus.APPROVAL_REQUIRED:
        code = 409
    raise HTTPException(code, detail={"error": result.error or result.status, "code": result.code, "data": result.data})


@files_router.get("/projects")
async def list_projects(request: Request) -> dict[str, Any]:
    rows = await _c(request).memory.list_projects()
    return {
        "projects": [
            {"id": r["id"], "name": r["name"], "path": r["path"], "last_opened": r["updated_at"]}
            for r in rows
        ]
    }


@files_router.get("/files")
async def list_files(request: Request, path: str = ".") -> dict[str, Any]:
    tools, ws, _cont = _tools(request)
    result = await tools.filesystem.handle("list_directory", {"path": path}, _ctx(ws))
    return _payload(result)


@files_router.get("/files/read")
async def read_file(request: Request, path: str) -> dict[str, Any]:
    tools, ws, _cont = _tools(request)
    result = await tools.filesystem.handle("read_file", {"path": path}, _ctx(ws))
    return _payload(result)


@files_router.put("/files")
async def write_file(body: FileBody, request: Request) -> dict[str, Any]:
    return await _run_tool(request, "write_file", {"path": body.path, "content": body.content})


@files_router.post("/files")
async def create_file(body: FileBody, request: Request) -> dict[str, Any]:
    return await _run_tool(request, "create_file", {"path": body.path, "content": body.content})


@files_router.post("/files/mkdir")
async def mkdir(body: PathBody, request: Request) -> dict[str, Any]:
    from app.permissions.sandbox import PathResolutionError

    tools, ws, _cont = _tools(request)
    try:
        result = await tools.filesystem.create_directory({"path": body.path}, _ctx(ws))
    except PathResolutionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return _payload(result)


@files_router.post("/files/rename")
async def rename_file(body: RenameBody, request: Request) -> dict[str, Any]:
    return await _run_tool(request, "rename_file", {"path": body.path, "new_path": body.new_path})


@files_router.post("/files/delete")
async def delete_file(body: PathBody, request: Request) -> dict[str, Any]:
    return await _run_tool(request, "delete_file", {"path": body.path})


@files_router.post("/files/delete-directory")
async def delete_directory(body: PathBody, request: Request) -> dict[str, Any]:
    """Delete a directory and all its contents.

    Uses the filesystem tool directly (not through policy/approval) since this
    endpoint is called from the Explorer UI where the user has already confirmed
    via a browser dialog.  The sandbox still enforces workspace boundaries.
    """
    tools, ws, _cont = _tools(request)
    try:
        result = await tools.filesystem.delete_directory({"path": body.path}, _ctx(ws))
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc
    return _payload(result)


@files_router.get("/search")
async def search(request: Request, q: str, mode: str = "code") -> dict[str, Any]:
    tools, ws, _cont = _tools(request)
    if mode == "files":
        result = await tools.search.handle("search_files", {"query": q}, _ctx(ws))
    elif mode == "symbol":
        result = await tools.search.handle("find_symbol", {"name": q}, _ctx(ws))
    else:
        result = await tools.search.handle("search_code", {"query": q}, _ctx(ws))
    return _payload(result)


@files_router.post("/terminal")
async def run_terminal(body: TerminalBody, request: Request) -> dict[str, Any]:
    args: dict[str, Any] = {"command": body.command}
    if body.timeout is not None:
        args["timeout"] = body.timeout
    tools, ws, _cont = _tools(request)
    validated = tools.validate_call({"tool": "run_terminal", "arguments": args})
    if isinstance(validated, ToolResult):
        _raise(validated)
    result = await tools.execute(validated, _ctx(ws))
    payload = result.as_model_content()
    payload["source"] = "user"
    if result.status != ToolStatus.SUCCESS:
        payload["ok"] = False
        return payload
    payload["ok"] = True
    return payload


@files_router.post("/dev/tests")
async def run_tests(request: Request) -> dict[str, Any]:
    return await _run_tool(request, "run_tests", {})


@files_router.get("/changes")
async def list_changes(request: Request) -> dict[str, Any]:
    tools, ws, cont = _tools(request)
    items: list[dict[str, Any]] = []
    for rel, original in list(cont.file_snapshots.items()):
        try:
            resolved = tools.filesystem.sandbox.resolve(rel)
        except Exception:
            continue
        current = ""
        if resolved.exists and resolved.absolute.is_file():
            try:
                current = resolved.absolute.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
        if current == original:
            continue
        diff = "".join(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                current.splitlines(keepends=True),
                fromfile=f"a/{rel}",
                tofile=f"b/{rel}",
            )
        )
        items.append({"path": rel, "original": original, "current": current, "diff": diff})
    return {"changes": items}


class SettingsBody(BaseModel):
    ollama_host: str | None = None
    preferred_model: str | None = None
    default_workspace: str | None = None
    ignore_directories: list[str] | None = None
    permission_mode: str | None = None
    auto_approve_yellow: bool | None = None
    appearance: str | None = None
    startup: str | None = None
    notifications: bool | None = None
    auto_route: bool | None = True
    log_level: str | None = None


@files_router.get("/settings")
async def get_settings(request: Request) -> dict[str, Any]:
    c = _c(request)
    s = c.settings
    extra = await _load_ui_settings(c)
    return {
        "ollama_host": s.ollama_host,
        "preferred_model": s.preferred_model,
        "default_workspace": s.default_workspace,
        "ignore_directories": s.ignore_directories,
        "permission_mode": s.permission_mode,
        "log_level": s.log_level,
        "auto_route": extra.get("auto_route", True),
        "auto_approve_yellow": extra.get("auto_approve_yellow", False),
        "appearance": extra.get("appearance", "dark"),
        "startup": extra.get("startup", "home"),
        "notifications": extra.get("notifications", True),
    }


@files_router.put("/settings")
async def put_settings(body: SettingsBody, request: Request) -> dict[str, Any]:
    c = _c(request)
    extra = await _load_ui_settings(c)
    data = body.model_dump(exclude_none=True)
    if "ollama_host" in data:
        c.settings.ollama_host = data["ollama_host"]
        from app.models.ollama import OllamaProvider

        if c.provider.name == "ollama":
            c.provider = OllamaProvider(c.settings.ollama_host, c.settings.ollama_timeout_seconds)
            c.model_registry.provider = c.provider
    if "preferred_model" in data:
        c.settings.preferred_model = data["preferred_model"]
        c.router.preferred = data["preferred_model"]
    if "default_workspace" in data:
        c.settings.default_workspace = data["default_workspace"]
    if "ignore_directories" in data:
        c.settings.ignore_directories = data["ignore_directories"]
    if "permission_mode" in data:
        c.settings.permission_mode = data["permission_mode"]
    if "log_level" in data:
        c.settings.log_level = data["log_level"]
    for key in ("auto_approve_yellow", "appearance", "startup", "notifications", "auto_route"):
        if key in data:
            extra[key] = data[key]
    await _save_ui_settings(c, extra)
    return await get_settings(request)


async def _load_ui_settings(c: AppContainer) -> dict[str, Any]:
    row = await c.db.fetch_one("SELECT content FROM memories WHERE kind = ? LIMIT 1", ("ui_settings",))
    if not row:
        return {}
    import json

    try:
        return json.loads(row["content"])
    except json.JSONDecodeError:
        return {}


async def _save_ui_settings(c: AppContainer, extra: dict[str, Any]) -> None:
    import json

    row = await c.db.fetch_one("SELECT id FROM memories WHERE kind = ? LIMIT 1", ("ui_settings",))
    content = json.dumps(extra)
    if row:
        await c.db.execute("UPDATE memories SET content = ? WHERE id = ?", (content, row["id"]))
    else:
        await c.memory.add_memory("ui", "ui_settings", content)


@files_router.post("/system/pick-folder")
async def pick_folder() -> dict[str, str]:
    import asyncio

    def _pick() -> str:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        chosen = filedialog.askdirectory(title="Choose project folder")
        root.destroy()
        return chosen or ""

    path = await asyncio.to_thread(_pick)
    return {"path": path}


# ── Project context scaffold ───────────────────────────────────────────────────

_DEFAULT_INSTRUCTIONS = """\
# Project Instructions for Po

<!-- Po reads this file before every task in this workspace. -->
<!-- Use it to define project-specific rules and context.    -->

## Stack
<!-- Describe the tech stack, e.g.: -->
<!-- Python 3.12, FastAPI, SQLite, React, TypeScript, Vite   -->

## Conventions
<!-- List important conventions, e.g.: -->
<!-- - Run `pytest tests/ -q` after backend changes           -->
<!-- - Run `npm run build` after frontend changes             -->
<!-- - Never modify production environment variables          -->

## Important Notes
<!-- Anything Po must always know about this project          -->
"""


@files_router.get("/project/instructions")
async def get_project_instructions(request: Request) -> dict[str, Any]:
    """Read .po/instructions.md for the active workspace."""
    tools, ws, _cont = _tools(request)
    po_dir = tools.filesystem.sandbox.workspace / ".po"
    inst_file = po_dir / "instructions.md"
    if not inst_file.exists():
        return {"exists": False, "content": ""}
    try:
        content = inst_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"exists": True, "content": ""}
    return {"exists": True, "content": content}


@files_router.post("/project/instructions/scaffold")
async def scaffold_project_instructions(request: Request) -> dict[str, Any]:
    """Create .po/instructions.md with a template if it does not already exist."""
    tools, ws, _cont = _tools(request)
    po_dir = tools.filesystem.sandbox.workspace / ".po"
    inst_file = po_dir / "instructions.md"
    if inst_file.exists():
        return {"created": False, "path": ".po/instructions.md"}
    try:
        po_dir.mkdir(parents=True, exist_ok=True)
        inst_file.write_text(_DEFAULT_INSTRUCTIONS, encoding="utf-8")
    except OSError as exc:
        raise HTTPException(500, f"Could not create .po/instructions.md: {exc}") from exc
    return {"created": True, "path": ".po/instructions.md"}


# ── Hooks CRUD ────────────────────────────────────────────────────────────────

from app.hooks.manager import delete_hook, list_hooks, save_hook  # noqa: E402


@files_router.get("/hooks")
async def get_hooks(request: Request) -> dict[str, Any]:
    c = _c(request)
    ws = c.workspace.active
    if not ws:
        return {"hooks": []}
    return {"hooks": await list_hooks(c.memory, ws.id)}


class HookBody(BaseModel):
    id: str | None = None
    name: str = ""
    trigger: str
    matcher: str | None = None
    action: dict[str, Any]


@files_router.post("/hooks")
async def upsert_hook(body: HookBody, request: Request) -> dict[str, Any]:
    c = _c(request)
    ws = c.workspace.active
    if not ws:
        raise HTTPException(400, "No active workspace")
    hook = body.model_dump(exclude_none=True)
    await save_hook(c.memory, ws.id, hook)
    return {"ok": True, "hook": hook}


@files_router.delete("/hooks/{hook_id}")
async def remove_hook(hook_id: str, request: Request) -> dict[str, Any]:
    c = _c(request)
    ws = c.workspace.active
    if not ws:
        raise HTTPException(400, "No active workspace")
    deleted = await delete_hook(c.memory, ws.id, hook_id)
    return {"ok": deleted}
