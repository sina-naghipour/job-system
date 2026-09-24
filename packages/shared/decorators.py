import functools
import logging
from typing import Awaitable, Callable

log = logging.getLogger(__name__)

ExecutionResult = tuple[int, str, str]
ExecutionFn = Callable[..., Awaitable[ExecutionResult]]


def capture_execution_errors(fn: ExecutionFn) -> ExecutionFn:
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs) -> ExecutionResult:
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:
            log.exception("Execution failed: %s", exc)
            return 1, "", str(exc)

    return wrapper