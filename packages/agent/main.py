import asyncio
import json
import logging
import os

import docker
import websockets
from websockets.client import WebSocketClientProtocol

from packages.shared.protocol import (
    JobMessage,
    ResultMessage,
    ServerToAgent,
)

log = logging.getLogger(__name__)


class DockerExecutor:
    """Runs a Job as a Docker container and returns its result."""

    def __init__(self) -> None:
        self._client = self._connect()

    def _connect(self) -> docker.DockerClient:
        try:
            client = docker.from_env()
            client.ping()
            return client
        except docker.errors.DockerException as exc:
            raise SystemExit(
                "Cannot connect to Docker. Is Docker Desktop running?\n"
                f"Underlying error: {exc}"
            )

    async def run(self, image: str, command: list[str]) -> tuple[int, str, str]:
        return await asyncio.to_thread(self._run_blocking, image, command)

    def _run_blocking(self, image: str, command: list[str]) -> tuple[int, str, str]:
        container = self._client.containers.run(
            image=image,
            command=command,
            detach=True,
            stdout=True,
            stderr=True,
        )
        try:
            result = container.wait()
            stdout = container.logs(stdout=True, stderr=False).decode()
            stderr = container.logs(stdout=False, stderr=True).decode()
            return int(result["StatusCode"]), stdout, stderr
        finally:
            container.remove(force=True)


class Agent:
    """Connects to the Server, receives Jobs, executes them, reports results."""

    def __init__(
        self,
        agent_id: str,
        server_url: str,
        executor: DockerExecutor,
    ) -> None:
        self._agent_id = agent_id
        self._server_url = server_url
        self._executor = executor

    async def run(self) -> None:
        async with websockets.connect(self._server_url) as ws:
            await self._register(ws)
            await self._listen(ws)

    async def _register(self, ws: WebSocketClientProtocol) -> None:
        await ws.send(json.dumps({
            "type": "register",
            "agent_id": self._agent_id,
        }))
        log.info("Registered as %s at %s", self._agent_id, self._server_url)

    async def _listen(self, ws: WebSocketClientProtocol) -> None:
        async for raw in ws:
            message: ServerToAgent = json.loads(raw)
            await self._dispatch(ws, message)

    async def _dispatch(self, ws: WebSocketClientProtocol, message: ServerToAgent) -> None:
        handlers = {
            "job": self._on_job,
            "cancel": self._on_cancel,
        }
        handler = handlers.get(message["type"])
        if handler is None:
            log.warning("Unknown message type: %s", message["type"])
            return
        await handler(ws, message)

    async def _on_job(self, ws: WebSocketClientProtocol, message: JobMessage) -> None:
        job_id = message["job_id"]
        log.info("Received job %s: image=%s", job_id, message["image"])

        await ws.send(json.dumps({"type": "ack", "job_id": job_id}))
        await ws.send(json.dumps({"type": "started", "job_id": job_id}))

        try:
            exit_code, stdout, stderr = await self._executor.run(
                message["image"], message["command"]
            )
            error = None
        except Exception as exc:
            log.exception("Job %s failed to run", job_id)
            exit_code, stdout, stderr = 1, "", str(exc)
            error = str(exc)

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

    async def _on_cancel(self, ws: WebSocketClientProtocol, message: dict) -> None:
        # Cancellation arrives in Phase 2.
        log.warning("Cancel not yet implemented for %s", message["job_id"])


def configure_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s [agent] %(levelname)s %(message)s",
    )


async def main() -> None:
    configure_logging()
    executor = DockerExecutor()
    agent = Agent(
        agent_id=os.getenv("AGENT_ID", "agent-1"),
        server_url=os.getenv("SERVER_URL", "ws://localhost:8080"),
        executor=executor,
    )
    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())