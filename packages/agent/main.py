import asyncio
import json
import logging
import os
from typing import AsyncGenerator, Optional

import docker
import websockets
from websockets.asyncio.client import ClientConnection

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

    async def start(self, image: str, command: list[str]):
        return await asyncio.to_thread(self._start_blocking, image, command)

    def _start_blocking(self, image: str, command: list[str]):
        return self._client.containers.run(
            image=image,
            command=command,
            detach=True,
            stdout=True,
            stderr=True,
        )

    async def stream_logs(self, container) -> AsyncGenerator[tuple[str, str], None]:
        stream = container.logs(stream=True, follow=True, stdout=True, stderr=True)
        try:
            while True:
                chunk = await asyncio.to_thread(next, stream, None)
                if chunk is None:
                    break
                if isinstance(chunk, bytes):
                    text = chunk.decode("utf-8", errors="replace")
                else:
                    text = str(chunk)
                if text:
                    yield "stdout", text
        finally:
            try:
                stream.close()
            except Exception:
                log.exception("Failed to close log stream")

    async def wait(self, container) -> tuple[int, str, str]:
        return await asyncio.to_thread(self._wait_blocking, container)

    def _wait_blocking(self, container) -> tuple[int, str, str]:
        try:
            result = container.wait()
            stdout = container.logs(stdout=True, stderr=False).decode()
            stderr = container.logs(stdout=False, stderr=True).decode()
            return int(result["StatusCode"]), stdout, stderr
        finally:
            try:
                container.remove(force=True)
            except Exception:
                log.exception("Failed to remove container")

    async def kill(self, container) -> None:
        await asyncio.to_thread(self._kill_blocking, container)

    def _kill_blocking(self, container) -> None:
        try:
            container.kill()
        except Exception:
            log.exception("Failed to kill container")


class Agent:
    def __init__(
        self,
        agent_id: str,
        server_url: str,
        executor: DockerExecutor,
    ) -> None:
        self._agent_id = agent_id
        self._server_url = server_url
        self._executor = executor
        self._running: dict[str, object] = {}
        self._sequences: dict[str, int] = {}

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

        try:
            container = await self._executor.start(
                message["image"], message["command"]
            )
        except Exception as exc:
            log.exception("Failed to start container for %s", job_id)
            await self._send_result(ws, job_id, 1, "", str(exc), error=str(exc))
            return

        self._running[job_id] = container
        self._sequences[job_id] = 0

        await ws.send(json.dumps({"type": "started", "job_id": job_id}))

        streaming = asyncio.create_task(self._stream(ws, job_id, container))
        try:
            exit_code, stdout, stderr = await self._executor.wait(container)
        finally:
            self._running.pop(job_id, None)
            streaming.cancel()
            try:
                await streaming
            except (asyncio.CancelledError, Exception):
                pass

        await self._send_result(ws, job_id, exit_code, stdout, stderr)

    async def _stream(self, ws: ClientConnection, job_id: str, container) -> None:
        try:
            async for stream, chunk in self._executor.stream_logs(container):
                seq = self._sequences.get(job_id, 0) + 1
                self._sequences[job_id] = seq
                await ws.send(json.dumps({
                    "type": "log",
                    "job_id": job_id,
                    "stream": stream,
                    "sequence": seq,
                    "chunk": chunk,
                }))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Log streaming failed for %s", job_id)
        finally:
            self._sequences.pop(job_id, None)

    async def _on_cancel(self, ws: ClientConnection, message: dict) -> None:
        job_id = message["job_id"]
        reason = message.get("reason", "unknown")
        log.info("Cancel requested for %s (reason=%s)", job_id, reason)

        container = self._running.get(job_id)
        if container is None:
            log.warning("No running container for %s", job_id)
            return
        await self._executor.kill(container)

    async def _send_result(
        self,
        ws: ClientConnection,
        job_id: str,
        exit_code: int,
        stdout: str,
        stderr: str,
        error: Optional[str] = None,
    ) -> None:
        if error is None and exit_code != 0:
            error = stderr or f"exit code {exit_code}"
        result = {
            "type": "result",
            "job_id": job_id,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "error": error,
        }
        await ws.send(json.dumps(result))
        log.info("Job %s finished with exit_code=%s", job_id, exit_code)


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