"""Tests for ecfs.core.queue — MessageQueue + MessagePriority."""

import asyncio
import time

from ecfs.core.queue import MessagePriority, MessageQueue


class TestMessageQueue:
    """Unit tests for the priority message queue."""

    async def test_enqueue_dequeue(self) -> None:
        q = MessageQueue()
        ok = await q.enqueue(b"hello", b"\x01")
        assert ok is True
        msg = await q.dequeue()
        assert msg is not None
        assert msg.data == b"hello"
        assert msg.message_id == b"\x01"

    async def test_priority_ordering(self) -> None:
        q = MessageQueue()
        # Enqueue normal first, then critical
        await q.enqueue(b"normal", b"\x01", MessagePriority.NORMAL)
        await q.enqueue(b"critical", b"\x02", MessagePriority.CRITICAL)
        # Critical should come out first
        first = await q.dequeue()
        assert first is not None
        assert first.data == b"critical"
        second = await q.dequeue()
        assert second is not None
        assert second.data == b"normal"

    async def test_queue_full_drops(self) -> None:
        q = MessageQueue(max_size=2)
        await q.enqueue(b"a", b"\x01")
        await q.enqueue(b"b", b"\x02")
        ok = await q.enqueue(b"c", b"\x03")
        assert ok is False
        assert q.dropped_count == 1

    async def test_expired_messages_dropped(self) -> None:
        q = MessageQueue(max_age_seconds=0)  # expire immediately
        await q.enqueue(b"old", b"\x01")
        # Artificially backdate the message
        msg = await q.dequeue()
        # Re-enqueue with backdated timestamp
        from ecfs.core.queue import QueuedMessage

        q._queue.put_nowait(
            QueuedMessage(
                priority=MessagePriority.NORMAL,
                created_at=time.time() - 100,
                data=b"expired",
                message_id=b"\x02",
            )
        )
        result = await q.dequeue()
        assert result is None
        assert q.dropped_count >= 1

    async def test_clear(self) -> None:
        q = MessageQueue()
        await q.enqueue(b"x", b"\x01")
        await q.enqueue(b"y", b"\x02")
        q.clear()
        assert q.size == 0
        assert q.dropped_count == 0
