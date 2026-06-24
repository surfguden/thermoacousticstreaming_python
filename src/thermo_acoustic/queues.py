from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque

from .messages import Message, QueueResult


@dataclass(slots=True)
class LabViewQueue:
    """Small adapter for the LabVIEW message queue behavior."""

    name: str
    _items: Deque[Message] = field(default_factory=deque)

    def enqueue(self, message: Message) -> None:
        if message.priority:
            self._items.appendleft(message)
        else:
            self._items.append(message)

    def dequeue(self, timeout_ms: int = -1) -> QueueResult:
        # This synchronous port does not block; callers with timeout-based wait
        # behavior poll through Application.wait().
        _ = timeout_ms
        message = self._items.popleft() if self._items else None
        return QueueResult(message=message, elements_remaining=len(self._items))

    def peek(self) -> QueueResult:
        message = self._items[0] if self._items else None
        return QueueResult(message=message, elements_remaining=len(self._items))

    def flush(self) -> list[Message]:
        remaining = list(self._items)
        self._items.clear()
        return remaining

    def __len__(self) -> int:
        return len(self._items)
