"""SSE event emitter with ring buffer for reconnection."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class SSEEvent:
    id: int
    event: str
    data: dict

    def encode(self) -> str:
        return f"id: {self.id}\nevent: {self.event}\ndata: {json.dumps(self.data)}\n\n"


class EventEmitter:
    """Per-job SSE event emitter with a ring buffer and subscriber notification."""

    def __init__(self, buffer_size: int = 200):
        self._buffer: deque[SSEEvent] = deque(maxlen=buffer_size)
        self._counter = 0
        self._subscribers: list[asyncio.Queue[SSEEvent | None]] = []
        self._closed = False

    def emit(self, event: str, data: dict) -> SSEEvent:
        """Emit an event to all subscribers and store in ring buffer."""
        self._counter += 1
        sse_event = SSEEvent(id=self._counter, event=event, data=data)
        self._buffer.append(sse_event)
        for q in self._subscribers:
            q.put_nowait(sse_event)
        return sse_event

    def subscribe(self, last_event_id: int | None = None) -> asyncio.Queue[SSEEvent | None]:
        """Create a new subscriber queue.

        If last_event_id is provided, replay missed events from the ring buffer.
        """
        q: asyncio.Queue[SSEEvent | None] = asyncio.Queue()

        if last_event_id is not None:
            for evt in self._buffer:
                if evt.id > last_event_id:
                    q.put_nowait(evt)

        if self._closed:
            q.put_nowait(None)
        else:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[SSEEvent | None]) -> None:
        """Remove a subscriber queue."""
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    def close(self) -> None:
        """Signal all subscribers that no more events are coming."""
        self._closed = True
        for q in self._subscribers:
            q.put_nowait(None)
        self._subscribers.clear()

    def snapshot(self) -> list[SSEEvent]:
        """Return all events currently in the ring buffer."""
        return list(self._buffer)


@dataclass
class EventRegistry:
    """Global registry of per-job event emitters."""

    _emitters: dict[str, EventEmitter] = field(default_factory=dict)

    def get_or_create(self, job_id: str, buffer_size: int = 200) -> EventEmitter:
        if job_id not in self._emitters:
            self._emitters[job_id] = EventEmitter(buffer_size=buffer_size)
        return self._emitters[job_id]

    def get(self, job_id: str) -> EventEmitter | None:
        return self._emitters.get(job_id)

    def remove(self, job_id: str) -> None:
        emitter = self._emitters.pop(job_id, None)
        if emitter:
            emitter.close()


event_registry = EventRegistry()
