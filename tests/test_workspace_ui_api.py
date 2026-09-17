from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.main import create_app
from app.models.mock import MockModelProvider


def test_files_search_terminal_projects_settings(tmp_path: Path) -> None:
    project = tmp_path / "ws"
    project.mkdir()
    (project / "hello.py").write_text("print('hi')\n", encoding="utf-8")
    settings = Settings(database_path=str(tmp_path / "po.db"), log_level="WARNING")
    app = create_app(settings, provider=MockModelProvider())
    with TestClient(app) as client:
        opened = client.post("/api/workspaces/open", json={"path": str(project), "name": "ws"})
        assert opened.status_code == 200
        listed = client.get("/api/projects")
        assert listed.status_code == 200
        assert any(p["name"] == "ws" for p in listed.json()["projects"])
        files = client.get("/api/files", params={"path": "."})
        assert files.status_code == 200
        assert any(e["name"] == "hello.py" for e in files.json()["entries"])
        read = client.get("/api/files/read", params={"path": "hello.py"})
        assert "print" in read.json()["content"]
        written = client.put("/api/files", json={"path": "hello.py", "content": "print('yo')\n"})
        assert written.status_code == 200
        created = client.post("/api/files", json={"path": "new.py", "content": "x=1\n"})
        assert created.status_code == 200
        mkdir = client.post("/api/files/mkdir", json={"path": "src"})
        assert mkdir.status_code == 200
        search = client.get("/api/search", params={"q": "print", "mode": "code"})
        assert search.status_code == 200
        assert search.json()["matches"]
        changes = client.get("/api/changes")
        assert changes.status_code == 200
        assert any(c["path"] == "hello.py" for c in changes.json()["changes"])
        escaped = client.get("/api/files/read", params={"path": "../secret.txt"})
        assert escaped.status_code in {400, 403, 404}
        settings_get = client.get("/api/settings")
        assert settings_get.status_code == 200
        saved = client.put("/api/settings", json={"appearance": "dark", "startup": "last"})
        assert saved.json()["appearance"] == "dark"
        term = client.post("/api/terminal", json={"command": "git --version"})
        assert term.status_code == 200
        assert "source" in term.json()
