from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config.settings import Settings, reset_settings
from app.container import AppContainer
from app.memory.database import Database
from app.models.mock import MockModelProvider


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    reset_settings()
    return Settings(
        database_path=str(tmp_path / "po.db"),
        ollama_host="http://127.0.0.1:11434",
        agent_max_iterations=20,
        agent_task_timeout_seconds=60,
        command_timeout_seconds=15,
        command_output_limit_bytes=8000,
        log_level="WARNING",
    )


@pytest.fixture
async def db(settings: Settings) -> Database:
    database = Database(settings.database_path)
    await database.initialize()
    return database


@pytest.fixture
def mock_provider() -> MockModelProvider:
    return MockModelProvider()


@pytest.fixture
async def container(settings: Settings, db: Database, mock_provider: MockModelProvider) -> AppContainer:
    return AppContainer(settings, db, provider=mock_provider)


@pytest.fixture
def workspace_dir(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / "README.md").write_text("# sample\n", encoding="utf-8")
    return root
