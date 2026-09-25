import asyncio
import logging
from collections import deque
from typing import Optional

log = logging.getLogger(__name__)

HISTORY_CAP = 5000
SUBSCRIBER_QUEUE_CAP = 1000


class LogChunk:
    __slots__ = ("stream", "sequence", "chunk")

    def __init__(self, stream: str, sequence: int, chunk: str) -> None:
        self.stream = stream
        self.sequence = sequence
        self.chunk = chunk


class LogBroker:
    def __init__(
        self,
        history_cap: int = HISTORY_CAP,
        queue_cap: int = SUBSCRIBER_QUEUE_CAP,
    ) -> None:
        self._history_cap = history_cap
        self._queue_cap = queue_cap
        self._history: dict[str, deque[LogChunk]] = {}
        self._sequences: dict[tuple[str, str], int] = {}
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._overflow_warned: set[str] = set()

    def publish(self, job_id: str, stream: str, chunk: str) -> LogChunk:
        key = (job_id, stream)
        sequence = self._sequences.get(key, 0) + 1
        self._sequences[key] = sequence

        entry = LogChunk(stream=stream, sequence=sequence, chunk=chunk)

        history = self._history.setdefault(job_id, deque(maxlen=self._history_cap))
        history.append(entry)

        for queue in self._subscribers.get(job_id, set()):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                if job_id not in self._overflow_warned:
                    log.warning("Subscriber queue overflow for %s; dropping oldest", job_id)
                    self._overflow_warned.add(job_id)
            try:
                queue.put_nowait(entry)
            except asyncio.QueueFull:
                pass

        return entry

    def subscribe(self, job_id: str) -> tuple[asyncio.Queue, list[LogChunk]]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._queue_cap)
        self._subscribers.setdefault(job_id, set()).add(queue)
        history = list(self._history.get(job_id, ()))
        return queue, history

    def unsubscribe(self, job_id: str, queue: asyncio.Queue) -> None:
        subscribers = self._subscribers.get(job_id)
        if not subscribers:
            return
        subscribers.discard(queue)
        if not subscribers:
            self._subscribers.pop(job_id, None)

    def history(self, job_id: str) -> list[LogChunk]:
        return list(self._history.get(job_id, ()))