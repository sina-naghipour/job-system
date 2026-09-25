import asyncio

import pytest
import websockets

from packages.agent.main import Agent
from packages.server.gateway import AgentGateway
from packages.server.store import (
    AgentRegistry,
    InMemoryJobRepository,
    JobService,
)


class StubContainer:
    def __init__(self) -> None:
        self.killed = False

    def kill(self) -> None:
        self.killed = True

    def remove(self, force: bool = False) -> None:
        pass

    def wait(self) -> dict:
        return {"StatusCode": 0}

    def logs(self, stdout: bool = True, stderr: bool = False) -> bytes:
        return b"stub output" if stdout else b""


class StubExecutor:
    def __init__(self) -> None:
        self._container = StubContainer()

    async def start(self, image: str, command: list[str]) -> StubContainer:
        return self._container

    async def wait(self, container) -> tuple[int, str, str]:
        return 0, "stub output", ""

    async def kill(self, container) -> None:
        container.kill()


@pytest.mark.integration
async def test_full_round_trip() -> None:
    service = JobService(InMemoryJobRepository())
    registry = AgentRegistry()
    gateway = AgentGateway(service, registry, host="127.0.0.1", port=0)

    server = await websockets.serve(gateway._handle_connection, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    agent = Agent("agent-1", f"ws://127.0.0.1:{port}", StubExecutor())
    agent_task = asyncio.create_task(agent.run())

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

    agent_task.cancel()
    server.close()
    await server.wait_closed()