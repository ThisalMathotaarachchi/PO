from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.events.types import AgentEvent

ws_router = APIRouter()


@ws_router.websocket("/ws/events")
async def event_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    container = websocket.app.state.container
    queue = container.bus.subscribe_queue()
    try:
        await websocket.send_json({"type": "connected"})
        while True:
            event: AgentEvent = await queue.get()
            await websocket.send_json(event.to_record())
    except WebSocketDisconnect:
        pass
    finally:
        container.bus.unsubscribe_queue(queue)
