"""In-process event bus. Agent core publishes; API/UI subscribe."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from app.events.types import AgentEvent, EventType
from app.logging_setup import get_logger

Listener = Callable[[AgentEvent], Awaitable[None] | None]


class EventBus:
    def __init__(self) -> None:
        self._listeners: dict[EventType | None, list[Listener]] = defaultdict(list)
        self._history: list[AgentEvent] = []
        self._lock = asyncio.Lock()
        self._log = get_logger("events")
        self._queues: list[asyncio.Queue[AgentEvent]] = []

    def subscribe(self, listener: Listener, event_type: EventType | None = None) -> None:
        self._listeners[event_type].append(listener)

    def subscribe_queue(self) -> asyncio.Queue[AgentEvent]:
        queue: asyncio.Queue[AgentEvent] = asyncio.Queue()
        self._queues.append(queue)
        return queue

    def unsubscribe_queue(self, queue: asyncio.Queue[AgentEvent]) -> None:
        if queue in self._queues:
            self._queues.remove(queue)

    async def publish(self, event: AgentEvent) -> AgentEvent:
        async with self._lock:
            self._history.append(event)
        self._log.debug(
            "event",
            extra={"extra_data": {"type": event.type, "task_id": event.task_id, "message": event.message}},
        )
        listeners = list(self._listeners.get(None, [])) + list(self._listeners.get(event.type, []))
        for listener in listeners:
            try:
                result = listener(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                self._log.exception("event listener failed")
        for queue in list(self._queues):
            await queue.put(event)
        return event

    async def emit(
        self,
        event_type: EventType,
        *,
        task_id: str | None = None,
        message: str = "",
        status: str = "ok",
        path: str | None = None,
        tool: str | None = None,
        command: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentEvent:
        event = AgentEvent(
            type=event_type,
            task_id=task_id,
            message=message,
            status=status,
            path=path,
            tool=tool,
            command=command,
            metadata=metadata or {},
        )
        return await self.publish(event)

    def recent(self, task_id: str | None = None, limit: int = 100) -> Sequence[AgentEvent]:
        items = self._history
        if task_id:
            items = [e for e in items if e.task_id == task_id]
        return items[-limit:]
