"""Po FastAPI application entrypoint."""

from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config.settings import Settings, get_settings
from app.container import AppContainer
from app.api.routes import router
from app.api.terminal_sessions import TerminalSessionManager, terminal_sessions_router
from app.api.websocket import ws_router
from app.api.workspace_io import files_router
from app.logging_setup import setup_logging
from app.memory.database import Database
from app.models.base import ModelProvider


def create_app(settings: Settings | None = None, provider: ModelProvider | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = Database(settings.resolve_database_path())
        await db.initialize()
        app.state.container = AppContainer(settings, db, provider=provider)
        terminal_mgr = TerminalSessionManager()
        app.state.terminal_manager = terminal_mgr
        yield
        # Clean up all terminal sessions on shutdown
        await terminal_mgr.cleanup_all()

    application = FastAPI(title="Po", version="0.1.0", lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(router, prefix="/api")
    application.include_router(files_router, prefix="/api")
    application.include_router(ws_router, prefix="/api")
    application.include_router(terminal_sessions_router, prefix="/api")

    @application.get("/api/meta")
    async def root() -> dict[str, Any]:
        return {"name": "Po", "docs": "/docs", "health": "/api/health"}

    dist = Path(__file__).resolve().parents[2] / "desktop" / "dist"
    if dist.exists():
        application.mount("/", StaticFiles(directory=str(dist), html=True), name="ui")

    return application


app = create_app()


def cli() -> None:
    parser = argparse.ArgumentParser(description="Po local agent backend")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=args.host or settings.host,
        port=args.port or settings.port,
        reload=False,
    )


if __name__ == "__main__":
    cli()
