"""
Persistent PowerShell terminal sessions backed by a real PTY (pywinpty).

Architecture
------------
Each TerminalSessionManager instance owns a dict of live sessions keyed by
session_id.  A session wraps a winpty PtyProcess (PowerShell on Windows).

WebSocket lifecycle (per session):
  1. POST   /api/terminal/sessions           → create session, return {id, label}
  2. GET    /api/terminal/sessions           → list all live sessions
  3. DELETE /api/terminal/sessions/{id}      → terminate + clean up
  4. WS     /api/terminal/sessions/{id}/ws  → attach, stream stdout/stdin

The read loop runs in a ThreadPoolExecutor because winpty.read() blocks.
Output chunks are placed on an asyncio.Queue that the WebSocket drainer
consumes.  Input from the WebSocket is written directly to the PTY.

Control frames from the frontend (JSON text frames):
  {"type":"resize","cols":N,"rows":N}   → resize PTY
  {"type":"ctrl","key":"c"}             → send Ctrl+C (ETX)
  {"type":"ctrl","key":"d"}             → send Ctrl+D (EOT)

All other text frames → written verbatim to PTY stdin.
Binary frames → written verbatim to PTY stdin.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

logger = logging.getLogger("po.terminal")

# ── PTY backend ────────────────────────────────────────────────────────────────

try:
    from winpty import PtyProcess as _PtyProcess  # pywinpty ≥ 3.x  (installed as 'winpty' module)
    _PTY_AVAILABLE = True
except ImportError:
    _PtyProcess = None  # type: ignore[assignment]
    _PTY_AVAILABLE = False
    logger.warning("pywinpty not installed — persistent terminal sessions unavailable")

_POWERSHELL = os.environ.get("PO_SHELL", "powershell.exe")
_SHELL_ARGS = ["-NoLogo", "-NoProfile"]
_DEFAULT_COLS = 220
_DEFAULT_ROWS = 50

# ── Pydantic bodies ────────────────────────────────────────────────────────────

class CreateSessionBody(BaseModel):
    cwd: str | None = None
    label: str | None = None


# ── Session dataclass ──────────────────────────────────────────────────────────

@dataclass
class LiveSession:
    id: str
    label: str
    pty: Any                                    # PtyProcess | None
    output_queue: asyncio.Queue                 # Queue[bytes | None]
    _loop: asyncio.AbstractEventLoop = field(repr=False, default=None)  # type: ignore[assignment]
    _reader_task: asyncio.Task | None = field(repr=False, default=None)
    alive: bool = True

    def write(self, data: str | bytes) -> None:
        if not self.alive:
            return
        if isinstance(data, bytes):
            data = data.decode("utf-8", errors="replace")
        try:
            self.pty.write(data)
        except Exception:
            pass

    def resize(self, cols: int, rows: int) -> None:
        if not self.alive:
            return
        try:
            self.pty.setwinsize(rows, cols)
        except Exception:
            pass

    def terminate(self) -> None:
        self.alive = False
        try:
            self.pty.terminate()
        except Exception:
            pass
        # Signal the reader loop to exit via the event loop
        try:
            if self._loop and not self._loop.is_closed():
                asyncio.run_coroutine_threadsafe(self._put_sentinel(), self._loop)
        except Exception:
            pass

    async def _put_sentinel(self) -> None:
        try:
            await self.output_queue.put(None)
        except Exception:
            pass


# ── Session manager ────────────────────────────────────────────────────────────

class TerminalSessionManager:
    """Owns all live PTY sessions for the application lifetime."""

    def __init__(self) -> None:
        self._sessions: dict[str, LiveSession] = {}
        self._counter: int = 0
        self._executor = ThreadPoolExecutor(max_workers=20, thread_name_prefix="po-pty")

    def _next_label(self) -> str:
        self._counter += 1
        return f"PowerShell {self._counter}"

    async def create_session(
        self,
        cwd: str | None = None,
        label: str | None = None,
    ) -> LiveSession:
        if not _PTY_AVAILABLE:
            raise RuntimeError(
                "pywinpty is not installed. "
                "Run: pip install pywinpty"
            )

        sid = uuid.uuid4().hex[:12]
        lbl = label or self._next_label()
        loop = asyncio.get_event_loop()

        # Spawn the PTY in a thread to avoid blocking the event loop
        pty = await loop.run_in_executor(
            self._executor,
            lambda: _PtyProcess.spawn(
                [_POWERSHELL, *_SHELL_ARGS],
                dimensions=(_DEFAULT_ROWS, _DEFAULT_COLS),
                cwd=cwd,
            ),
        )

        q: asyncio.Queue = asyncio.Queue(maxsize=1024)
        session = LiveSession(id=sid, label=lbl, pty=pty, output_queue=q, _loop=loop)
        self._sessions[sid] = session

        # Start background reader task
        session._reader_task = asyncio.ensure_future(
            self._read_loop(session),
        )

        logger.info(
            "terminal session created",
            extra={"extra_data": {"id": sid, "label": lbl, "cwd": cwd}},
        )
        return session

    async def _read_loop(self, session: LiveSession) -> None:
        """Drain PTY output in a thread and forward to the asyncio queue."""
        loop = asyncio.get_event_loop()

        def _blocking_read() -> bytes | None:
            try:
                chunk = session.pty.read(4096)
                if chunk:
                    return chunk.encode("utf-8", errors="replace")
                return b""
            except EOFError:
                return None
            except Exception:
                return None

        while session.alive:
            chunk: bytes | None = await loop.run_in_executor(self._executor, _blocking_read)
            if chunk is None:
                # PTY process ended
                session.alive = False
                try:
                    await session.output_queue.put(None)
                except Exception:
                    pass
                break
            if chunk:
                try:
                    await asyncio.wait_for(session.output_queue.put(chunk), timeout=10.0)
                except asyncio.TimeoutError:
                    # Consumer not keeping up — drop this chunk rather than deadlock
                    pass

    def get_session(self, sid: str) -> LiveSession | None:
        return self._sessions.get(sid)

    async def remove_session(self, sid: str) -> None:
        session = self._sessions.pop(sid, None)
        if session:
            session.terminate()
            if session._reader_task and not session._reader_task.done():
                session._reader_task.cancel()
            logger.info(
                "terminal session removed",
                extra={"extra_data": {"id": sid}},
            )

    async def cleanup_all(self) -> None:
        for sid in list(self._sessions):
            await self.remove_session(sid)
        self._executor.shutdown(wait=False)


# ── FastAPI router ─────────────────────────────────────────────────────────────

terminal_sessions_router = APIRouter()


def _get_manager(app_state: Any) -> TerminalSessionManager:
    mgr = getattr(app_state, "terminal_manager", None)
    if mgr is None:
        raise HTTPException(503, "Terminal session manager not initialised")
    return mgr


@terminal_sessions_router.get("/terminal/sessions")
async def list_sessions(request: Request) -> dict:
    mgr = _get_manager(request.app.state)
    return {
        "sessions": [
            {"id": s.id, "label": s.label, "alive": s.alive}
            for s in mgr._sessions.values()
        ]
    }


@terminal_sessions_router.post("/terminal/sessions")
async def create_session(body: CreateSessionBody, request: Request) -> dict:
    mgr = _get_manager(request.app.state)
    try:
        session = await mgr.create_session(cwd=body.cwd, label=body.label)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"id": session.id, "label": session.label}


@terminal_sessions_router.delete("/terminal/sessions/{session_id}")
async def delete_session(session_id: str, request: Request) -> dict:
    mgr = _get_manager(request.app.state)
    if session_id not in mgr._sessions:
        raise HTTPException(404, "Session not found")
    await mgr.remove_session(session_id)
    return {"ok": True}


@terminal_sessions_router.websocket("/terminal/sessions/{session_id}/ws")
async def session_ws(session_id: str, websocket: WebSocket) -> None:
    """
    Bidirectional WS channel for a PTY terminal session.

    Server → Client:
        bytes  — raw PTY output (includes ANSI escape sequences)
        JSON   — {"type":"exit"} when the process terminates

    Client → Server (text frames):
        plain text  — written as-is to PTY stdin
        JSON {"type":"resize","cols":N,"rows":N} — resize PTY window
        JSON {"type":"ctrl","key":"c"/"d"/"z"}   — send control character

    Client → Server (binary frames):
        bytes — written as-is to PTY stdin
    """
    mgr = _get_manager(websocket.app.state)
    session = mgr.get_session(session_id)
    if session is None:
        await websocket.close(code=4004)
        return

    await websocket.accept()
    logger.debug("terminal WS connected", extra={"extra_data": {"id": session_id}})

    async def _drain_output() -> None:
        """Forward PTY output → WebSocket."""
        while True:
            try:
                chunk = await asyncio.wait_for(session.output_queue.get(), timeout=30.0)
            except asyncio.TimeoutError:
                # Keep-alive ping — send empty bytes; if it fails the WS is dead
                try:
                    await websocket.send_bytes(b"")
                except Exception:
                    break
                continue

            if chunk is None:
                # Process exited
                try:
                    await websocket.send_text(json.dumps({"type": "exit"}))
                except Exception:
                    pass
                break
            try:
                await websocket.send_bytes(chunk)
            except Exception:
                break

    async def _receive_input() -> None:
        """Forward WebSocket → PTY stdin."""
        while True:
            try:
                msg = await websocket.receive()
            except WebSocketDisconnect:
                break

            if msg.get("type") == "websocket.disconnect":
                break

            text: str | None = msg.get("text")
            data: bytes | None = msg.get("bytes")

            if text:
                # Attempt to parse as a control frame first
                try:
                    frame = json.loads(text)
                    ftype = frame.get("type")
                    if ftype == "resize":
                        cols = max(10, int(frame.get("cols", _DEFAULT_COLS)))
                        rows = max(4, int(frame.get("rows", _DEFAULT_ROWS)))
                        session.resize(cols, rows)
                        continue
                    if ftype == "ctrl":
                        key = str(frame.get("key", ""))
                        if key == "c":
                            session.write("\x03")
                        elif key == "d":
                            session.write("\x04")
                        elif key == "z":
                            session.write("\x1a")
                        continue
                except (json.JSONDecodeError, ValueError, TypeError):
                    pass
                # Regular keystroke / pasted text
                session.write(text)

            elif data:
                session.write(data)

    try:
        # Run both coroutines concurrently; either finishing stops the session
        done, pending = await asyncio.wait(
            [
                asyncio.ensure_future(_drain_output()),
                asyncio.ensure_future(_receive_input()),
            ],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
    except Exception as exc:
        logger.debug("terminal WS error: %s", exc)
    finally:
        logger.debug("terminal WS disconnected", extra={"extra_data": {"id": session_id}})
