from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app import __version__
from app.agent.task import Task
from app.api.schemas import (
    ApprovalBody,
    HealthResponse,
    TaskCreate,
    TaskView,
    WorkspaceCreate,
    WorkspaceOpen,
    WorkspaceView,
)
from app.container import AppContainer
from app.workspace.manager import WorkspaceError

router = APIRouter()


def container(request: Request) -> AppContainer:
    return request.app.state.container


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    c = container(request)
    ollama = await c.provider.health()
    db_ok = True
    try:
        await c.db.fetch_one("SELECT 1 AS ok")
    except Exception:
        db_ok = False
    return HealthResponse(ok=db_ok, database=db_ok, ollama=ollama, version=__version__)


@router.get("/status")
async def status(request: Request) -> dict[str, Any]:
    c = container(request)
    ws = c.workspace.active
    current = None
    if c.engine and c.engine._tasks:  # noqa: SLF001
        current = next(reversed(list(c.engine._tasks.values()))).public_dict()  # noqa: SLF001
    return {
        "workspace": ws.model_dump() if ws else None,
        "models_error": c.model_registry.last_error,
        "task": current,
    }


@router.post("/workspaces", response_model=WorkspaceView)
async def create_workspace(body: WorkspaceCreate, request: Request) -> WorkspaceView:
    c = container(request)
    try:
        ws = await c.workspace.create_project(body.path, body.name)
    except WorkspaceError as exc:
        raise HTTPException(400, str(exc)) from exc
    return WorkspaceView(id=ws.id, path=ws.path, name=ws.name)


@router.post("/workspaces/open", response_model=WorkspaceView)
async def open_workspace(body: WorkspaceOpen, request: Request) -> WorkspaceView:
    c = container(request)
    try:
        ws = await c.workspace.open_project(body.path, body.name)
    except WorkspaceError as exc:
        raise HTTPException(400, str(exc)) from exc
    return WorkspaceView(id=ws.id, path=ws.path, name=ws.name)


@router.get("/workspaces/active", response_model=WorkspaceView)
async def active_workspace(request: Request) -> WorkspaceView:
    ws = container(request).workspace.active
    if not ws:
        raise HTTPException(404, "No active workspace")
    return WorkspaceView(id=ws.id, path=ws.path, name=ws.name)


@router.get("/models")
async def list_models(request: Request) -> dict[str, Any]:
    c = container(request)
    try:
        models = await c.model_registry.refresh()
    except Exception as exc:
        return {"ok": False, "error": str(exc), "models": []}
    selected = None
    try:
        if models:
            selected = c.router.select(models).id
    except Exception as exc:
        return {"ok": True, "models": [m.model_dump() for m in models], "selected": None, "error": str(exc)}
    return {"ok": True, "models": [m.model_dump() for m in models], "selected": selected}


@router.post("/tasks", response_model=TaskView)
async def create_task(body: TaskCreate, request: Request) -> TaskView:
    c = container(request)
    path = body.workspace_path
    if path:
        try:
            ws = await c.workspace.open_project(path)
        except WorkspaceError as exc:
            raise HTTPException(400, str(exc)) from exc
    else:
        ws = c.workspace.active
        if not ws:
            raise HTTPException(400, "No active workspace")
    engine = c.engine_for(ws)
    session_id = await c.memory.create_session(ws.id)
    task = Task(prompt=body.prompt, project_id=ws.id, workspace_path=ws.path, session_id=session_id)
    asyncio.create_task(engine.run(task))
    return TaskView(**task.public_dict())


@router.get("/tasks/{task_id}", response_model=TaskView)
async def get_task(task_id: str, request: Request) -> TaskView:
    c = container(request)
    task = c.engine.get_task(task_id) if c.engine else None
    if not task:
        row = await c.memory.get_task(task_id)
        if not row:
            raise HTTPException(404, "Task not found")
        return TaskView(
            id=row["id"],
            prompt=row["prompt"],
            status=row["status"],
            summary=row.get("summary") or "",
            error=row.get("error") or "",
            model=row.get("model") or "",
            project_id=row.get("project_id") or "",
        )
    return TaskView(**task.public_dict())


@router.post("/tasks/{task_id}/cancel", response_model=TaskView)
async def cancel_task(task_id: str, request: Request) -> TaskView:
    c = container(request)
    if not c.engine:
        raise HTTPException(404, "No engine")
    task = await c.engine.cancel(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return TaskView(**task.public_dict())


@router.post("/tasks/{task_id}/approval", response_model=TaskView)
async def approve_task(task_id: str, body: ApprovalBody, request: Request) -> TaskView:
    c = container(request)
    if not c.engine:
        raise HTTPException(404, "No engine")
    task = await c.engine.approve(task_id, body.granted)
    if not task:
        raise HTTPException(404, "Task not found")
    return TaskView(**task.public_dict())


@router.get("/tasks/{task_id}/events")
async def task_events(task_id: str, request: Request, limit: int = 200) -> dict[str, Any]:
    c = container(request)
    live = [e.to_record() for e in c.bus.recent(task_id=task_id, limit=limit)]
    if live:
        return {"events": live}
    rows = await c.db.fetch_all(
        "SELECT payload FROM events WHERE task_id = ? ORDER BY id ASC LIMIT ?",
        (task_id, limit),
    )
    import json

    events = []
    for row in rows:
        try:
            events.append(json.loads(row["payload"]))
        except json.JSONDecodeError:
            continue
    return {"events": events}
