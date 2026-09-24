import asyncio
import json
import logging
import os

import docker
import websockets
from websockets.asyncio.client import ClientConnection

from packages.agent.decorators import send_result_to_server
from packages.shared.decorators import capture_execution_errors
from packages.shared.logging_config import configure_logging
from packages.shared.protocol import JobMessage, ServerToAgent

log = logging.getLogger(__name__)


class DockerExecutor:
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

    @capture_execution_errors
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
            try:
                container.remove(force=True)
            except Exception:
                log.exception("Failed to remove container for %s", image)


class Agent:
    def __init__(self, agent_id: str, server_url: str, executor: DockerExecutor) -> None:
        self._agent_id = agent_id
        self._server_url = server_url
        self._executor = executor

    async def run(self) -> None:
        async with websockets.connect(self._server_url) as ws:
            await self._register(ws)
            await self._listen(ws)

    async def _register(self, ws: ClientConnection) -> None:
        await ws.send(json.dumps({"type": "register", "agent_id": self._agent_id}))
        log.info("Registered as %s at %s", self._agent_id, self._server_url)

    async def _listen(self, ws: ClientConnection) -> None:
        async for raw in ws:
            try:
                message: ServerToAgent = json.loads(raw)
            except json.JSONDecodeError:
                log.warning("Ignoring malformed message: %r", raw[:200])
                continue
            await self._dispatch(ws, message)

    async def _dispatch(self, ws: ClientConnection, message: ServerToAgent) -> None:
        handlers = {
            "job": self._on_job,
            "cancel": self._on_cancel,
        }
        handler = handlers.get(message["type"])
        if handler is None:
            log.warning("Unknown message type: %s", message["type"])
            return
        await handler(ws, message)

    async def _on_job(self, ws: ClientConnection, message: JobMessage) -> None:
        job_id = message["job_id"]
        log.info("Received job %s: image=%s", job_id, message["image"])

        await ws.send(json.dumps({"type": "ack", "job_id": job_id}))
        await ws.send(json.dumps({"type": "started", "job_id": job_id}))

        await self._execute_and_report(ws, job_id, message["image"], message["command"])

    @send_result_to_server
    async def _execute_and_report(
        self,
        ws: ClientConnection,
        job_id: str,
        image: str,
        command: list[str],
    ) -> tuple[int, str, str]:
        return await self._executor.run(image, command)

    async def _on_cancel(self, ws: ClientConnection, message: dict) -> None:
        log.warning("Cancel not yet implemented for %s", message["job_id"])


async def main() -> None:
    configure_logging("agent")
    executor = DockerExecutor()
    agent = Agent(
        agent_id=os.getenv("AGENT_ID", "agent-1"),
        server_url=os.getenv("SERVER_URL", "ws://localhost:8080"),
        executor=executor,
    )
    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())