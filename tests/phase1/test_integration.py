import asyncio

import pytest
import websockets

from packages.agent.main import Agent
from packages.server.gateway import AgentGateway
from packages.server.log_broker import LogBroker
from packages.server.log_repository import SQLiteLogRepository
from packages.server.store import (
    AgentRegistry,
    InMemoryJobRepository,
    JobService,
)


class StubContainer:
    def __init__(self, job_id: str = "job_stub") -> None:
        self.killed = False
        self.labels = {"job_id": job_id, "managed_by": "job-system"}
        self.status = "running"

    def kill(self) -> None:
        self.killed = True

    def remove(self, force: bool = False) -> None:
        pass

    def wait(self) -> dict:
        return {"StatusCode": 0}

    def logs(
        self,
        stream: bool = False,
        follow: bool = False,
        stdout: bool = True,
        stderr: bool = False,
    ):
        if stream:
            return iter([b"stub output"]) if stdout else iter([])
        return b"stub output" if stdout else b""

    def reload(self) -> None:
        pass

    attrs = {"State": {"ExitCode": 0}}


class StubExecutor:
    def __init__(self) -> None:
        self._container = StubContainer()

    async def start(self, job_id: str, image: str, command: list[str]) -> StubContainer:
        return self._container

    async def stream_logs(self, container):
        yield "stdout", "stub output"

    async def wait(self, container) -> tuple[int, str, str]:
        return 0, "stub output", ""

    async def kill(self, container) -> None:
        container.kill()

    async def list_managed_containers(self) -> list:
        return []

    async def inspect_exited(self, container) -> tuple[int, str, str]:
        return 0, "stub output", ""

    async def remove(self, container) -> None:
        pass


@pytest.mark.integration
async def test_full_round_trip() -> None:
    service = JobService(InMemoryJobRepository())
    registry = AgentRegistry()
    broker = LogBroker()
    log_repo = SQLiteLogRepository(":memory:")

    gateway = AgentGateway(
        job_service=service,
        agent_registry=registry,
        log_broker=broker,
        log_repository=log_repo,
        host="127.0.0.1",
        port=0,
    )

    server = await websockets.serve(gateway._handle_connection, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    agent = Agent("agent-1", f"ws://127.0.0.1:{port}", StubExecutor())
    agent_task = asyncio.create_task(agent.run())

    try:
        for _ in range(50):
            if registry.is_online("agent-1"):
                break
            await asyncio.sleep(0.05)
        assert registry.is_online("agent-1")

        job = service.submit("agent-1", "alpine", ["echo"], 1000)
        await gateway.dispatch_pending("agent-1")

        for _ in range(50):
            fetched = service.get(job.job_id)
            if fetched and fetched.state.is_terminal:
                break
            await asyncio.sleep(0.05)

        fetched = service.get(job.job_id)
        assert fetched.state.value == "SUCCEEDED"
        assert fetched.stdout == "stub output"
    finally:
        agent_task.cancel()
        server.close()
        await server.wait_closed()
        log_repo.close()