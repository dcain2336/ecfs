"""Priority message queue for packets awaiting transmission."""

import asyncio
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional


class MessagePriority(IntEnum):
    """Message priority levels — lower number = higher priority."""

    CRITICAL = 0  # emergency, route immediately
    HIGH = 1  # time-sensitive
    NORMAL = 2  # default
    LOW = 3  # background/bulk


@dataclass(order=True)
class QueuedMessage:
    """A message sitting in the priority queue."""

    priority: MessagePriority
    created_at: float = field(compare=False, default_factory=time.time)
    data: bytes = field(compare=False, default=b"")
    message_id: bytes = field(compare=False, default=b"")
    retries: int = field(compare=False, default=0)


class MessageQueue:
    """Priority queue for packets awaiting transmission.

    Critical messages jump the queue. Includes retry tracking
    and TTL-aware dropping.
    """

    def __init__(self, max_size: int = 5000, max_age_seconds: int = 300) -> None:
        self._max_size = max_size
        self._max_age = max_age_seconds
        self._queue: asyncio.PriorityQueue[QueuedMessage] = asyncio.PriorityQueue(
            maxsize=max_size
        )
        self._dropped: int = 0

    async def enqueue(
        self,
        data: bytes,
        message_id: bytes,
        priority: MessagePriority = MessagePriority.NORMAL,
    ) -> bool:
        """Add a message. Returns False if queue is full."""
        msg = QueuedMessage(priority=priority, data=data, message_id=message_id)
        try:
            self._queue.put_nowait(msg)
            return True
        except asyncio.QueueFull:
            self._dropped += 1
            return False

    async def dequeue(self) -> Optional[QueuedMessage]:
        """Get next message, dropping expired ones."""
        while not self._queue.empty():
            try:
                msg = self._queue.get_nowait()
                age = time.time() - msg.created_at
                if age > self._max_age:
                    self._dropped += 1
                    continue
                return msg
            except asyncio.QueueEmpty:
                break
        return None

    @property
    def size(self) -> int:
        return self._queue.qsize()

    @property
    def dropped_count(self) -> int:
        return self._dropped

    def clear(self) -> None:
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._dropped = 0
