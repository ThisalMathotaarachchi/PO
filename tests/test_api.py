from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.main import create_app
from app.models.base import ModelResponse
from app.models.mock import MockModelProvider


def _complete() -> ModelResponse:
    return ModelResponse(content='{"complete": true, "summary": "Done."}')


def _client(tmp_path: Path, provider: MockModelProvider | None = None) -> TestClient:
    settings = Settings(database_path=str(tmp_path / "po.db"), log_level="WARNING", agent_max_iterations=8)
    app = create_app(settings, provider=provider or MockModelProvider(responses=[_complete()]))
    return TestClient(app)


def test_health_and_workspace(tmp_path: Path) -> None:
    project = tmp_path / "ws"
    project.mkdir()
    provider = MockModelProvider(responses=[_complete()])
    with _client(tmp_path, provider) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        body = health.json()
        assert body["database"] is True
        assert "ollama" in body
        created = client.post("/api/workspaces", json={"path": str(project), "name": "demo"})
        assert created.status_code == 200
        active = client.get("/api/workspaces/active")
        assert active.json()["path"] == str(project.resolve())
        models = client.get("/api/models")
        assert models.status_code == 200
        assert models.json()["ok"] is True


def test_task_status_cancel_and_events(tmp_path: Path) -> None:
    project = tmp_path / "ws"
    project.mkdir()
    (project / "a.py").write_text("x=1\n", encoding="utf-8")

    async def handler(messages):
        import asyncio

        await asyncio.sleep(0.2)
        return ModelResponse(tool_calls=[{"tool": "list_directory", "arguments": {"path": "."}}])

    provider = MockModelProvider(handler=handler)
    with _client(tmp_path, provider) as client:
        client.post("/api/workspaces/open", json={"path": str(project)})
        created = client.post("/api/tasks", json={"prompt": "look around"})
        assert created.status_code == 200
        task_id = created.json()["id"]
        status = client.get(f"/api/tasks/{task_id}")
        assert status.status_code == 200
        cancelled = client.post(f"/api/tasks/{task_id}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] in {"CANCELLED", "COMPLETED", "ERROR", "EXPLORING", "UNDERSTANDING", "PLANNING"}
        # allow loop to settle
        deadline = time.time() + 5
        final_status = ""
        while time.time() < deadline:
            final_status = client.get(f"/api/tasks/{task_id}").json()["status"]
            if final_status in {"CANCELLED", "COMPLETED", "ERROR"}:
                break
            time.sleep(0.05)
        assert final_status in {"CANCELLED", "COMPLETED", "ERROR"}
        events = client.get(f"/api/tasks/{task_id}/events")
        assert events.status_code == 200
        with client.websocket_connect("/api/ws/events") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "connected"
