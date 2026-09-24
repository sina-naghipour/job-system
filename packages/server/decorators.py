import functools
import json
import logging
from typing import Any, Awaitable, Callable

import websockets

log = logging.getLogger(__name__)

AsyncFn = Callable[..., Awaitable[Any]]


def with_connection_guard(fn: AsyncFn) -> AsyncFn:
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except websockets.ConnectionClosed:
            raise
        except Exception:
            log.exception("Unexpected error in connection handler")

    return wrapper


def with_dispatch_guard(fn: AsyncFn) -> AsyncFn:
    @functools.wraps(fn)
    async def wrapper(self, ws, message, agent_id, *args, **kwargs):
        try:
            return await fn(self, ws, message, agent_id, *args, **kwargs)
        except Exception:
            log.exception("Message handler failed")
            return agent_id

    return wrapper


def with_send_guard(fn: AsyncFn) -> AsyncFn:
    @functools.wraps(fn)
    async def wrapper(self, ws, message, *args, **kwargs):
        try:
            await fn(self, ws, message, *args, **kwargs)
            return True
        except websockets.ConnectionClosed:
            log.warning("Send failed: socket closed")
            return False

    return wrapper