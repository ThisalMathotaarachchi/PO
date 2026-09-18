"""Central configuration for Po. Paths are relative to the process working directory unless absolute."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_config_path() -> Path:
    env_path = Path.cwd() / "config" / "default.yaml"
    if env_path.exists():
        return env_path
    # Running from backend/ or installed package
    candidate = Path(__file__).resolve().parents[3] / "config" / "default.yaml"
    return candidate


def _load_yaml_defaults() -> dict[str, Any]:
    path = _default_config_path()
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        return {}
    return data


class Settings(BaseSettings):
    """Runtime settings. Environment variables use the PO_ prefix."""

    model_config = SettingsConfigDict(
        env_prefix="PO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ollama_host: str = "http://127.0.0.1:11434"
    ollama_timeout_seconds: float = 600.0
    ollama_generation_timeout_seconds: float = 1800.0
    preferred_model: str = ""
    database_path: str = "data/po.db"
    default_workspace: str = ""
    log_level: str = "INFO"
    agent_max_iterations: int = 50
    agent_task_timeout_seconds: float = 3600.0
    command_timeout_seconds: float = 120.0
    command_output_limit_bytes: int = 50_000
    file_read_limit_bytes: int = 100_000
    search_max_results: int = 50
    index_max_file_bytes: int = 1_048_576
    permission_mode: str = "standard"
    ignore_directories: list[str] = Field(
        default_factory=lambda: [
            ".git",
            "node_modules",
            ".venv",
            "venv",
            "__pycache__",
            "dist",
            "build",
            "coverage",
        ]
    )
    host: str = "127.0.0.1"
    port: int = 8000

    def resolve_database_path(self) -> Path:
        path = Path(self.database_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return path


def _merge_defaults() -> dict[str, Any]:
    data = _load_yaml_defaults()
    # YAML keys match field names
    return {k: v for k, v in data.items() if v is not None}


@lru_cache
def get_settings() -> Settings:
    defaults = _merge_defaults()
    return Settings(**defaults)


def reset_settings() -> None:
    get_settings.cache_clear()
