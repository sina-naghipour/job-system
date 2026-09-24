import functools
import json
import logging
from typing import Any, Awaitable, Callable, Protocol

from packages.shared.protocol import ResultMessage

log = logging.getLogger(__name__)


class WebSocket(Protocol):
    async def send(self, data: str) -> None: ...


JobHandler = Callable[[Any, WebSocket, str, str, list[str]], Awaitable[tuple[int, str, str]]]


def send_result_to_server(fn: JobHandler) -> JobHandler:
    @functools.wraps(fn)
    async def wrapper(
        self,
        ws: WebSocket,
        job_id: str,
        image: str,
        command: list[str],
    ) -> None:
        exit_code, stdout, stderr = await fn(self, ws, job_id, image, command)
        error = stderr if exit_code != 0 else None

        result: ResultMessage = {
            "type": "result",
            "job_id": job_id,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "error": error,
        }
        await ws.send(json.dumps(result))
        log.info("Job %s finished with exit_code=%s", job_id, exit_code)

    return wrapper