"""Tests for the SSE event system (architecture §6)."""

from __future__ import annotations

import asyncio

import pytest

from app.events.sse import EventEmitter, EventRegistry


class TestEventEmitter:
    def test_emit_and_subscribe_delivers_events(self):
        emitter = EventEmitter(buffer_size=50)
        q = emitter.subscribe()
        emitter.emit("test.event", {"key": "value"})

        event = q.get_nowait()
        assert event.event == "test.event"
        assert event.data == {"key": "value"}
        assert event.id == 1

    def test_monotonic_ids(self):
        emitter = EventEmitter(buffer_size=50)
        q = emitter.subscribe()
        emitter.emit("a", {})
        emitter.emit("b", {})
        emitter.emit("c", {})

        ids = [q.get_nowait().id for _ in range(3)]
        assert ids == [1, 2, 3]

    def test_ring_buffer_capacity(self):
        emitter = EventEmitter(buffer_size=50)
        for i in range(60):
            emitter.emit("evt", {"i": i})

        snapshot = emitter.snapshot()
        assert len(snapshot) == 50
        # Oldest event should be id=11 (first 10 evicted)
        assert snapshot[0].id == 11

    def test_reconnection_replay(self):
        emitter = EventEmitter(buffer_size=50)
        for i in range(10):
            emitter.emit("evt", {"i": i})

        # Subscribe with last_event_id=5, should replay events 6-10
        q = emitter.subscribe(last_event_id=5)
        replayed = []
        while not q.empty():
            replayed.append(q.get_nowait())

        assert len(replayed) == 5
        assert replayed[0].id == 6
        assert replayed[-1].id == 10

    def test_close_sends_none_to_subscribers(self):
        emitter = EventEmitter(buffer_size=50)
        q1 = emitter.subscribe()
        q2 = emitter.subscribe()

        emitter.close()

        assert q1.get_nowait() is None
        assert q2.get_nowait() is None

    def test_closed_emitter_new_subscriber_gets_none(self):
        emitter = EventEmitter(buffer_size=50)
        emitter.emit("before", {})
        emitter.close()

        q = emitter.subscribe()
        # Should get None immediately (possibly after replayed events)
        items = []
        while not q.empty():
            items.append(q.get_nowait())
        assert items[-1] is None

    def test_multiple_subscribers_receive_same_events(self):
        emitter = EventEmitter(buffer_size=50)
        q1 = emitter.subscribe()
        q2 = emitter.subscribe()

        emitter.emit("test", {"v": 1})

        e1 = q1.get_nowait()
        e2 = q2.get_nowait()
        assert e1.id == e2.id
        assert e1.data == e2.data

    def test_unsubscribe_stops_delivery(self):
        emitter = EventEmitter(buffer_size=50)
        q = emitter.subscribe()
        emitter.unsubscribe(q)
        emitter.emit("after", {})

        assert q.empty()

    def test_encode_format(self):
        emitter = EventEmitter(buffer_size=50)
        evt = emitter.emit("page.completed", {"page": 0})
        encoded = evt.encode()
        assert "id: 1" in encoded
        assert "event: page.completed" in encoded
        assert '"page": 0' in encoded


class TestEventRegistry:
    def test_get_or_create_is_idempotent(self):
        registry = EventRegistry()
        e1 = registry.get_or_create("job1", 50)
        e2 = registry.get_or_create("job1", 50)
        assert e1 is e2

    def test_get_returns_none_for_unknown(self):
        registry = EventRegistry()
        assert registry.get("nonexistent") is None

    def test_remove_closes_emitter(self):
        registry = EventRegistry()
        emitter = registry.get_or_create("job1", 50)
        q = emitter.subscribe()

        registry.remove("job1")

        assert q.get_nowait() is None
        assert registry.get("job1") is None
