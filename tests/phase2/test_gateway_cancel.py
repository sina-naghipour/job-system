import json

import pytest

from packages.server.gateway import AgentGateway
from packages.server.log_broker import LogBroker
from packages.server.log_repository import SQLiteLogRepository
from packages.server.store import (
    AgentRegistry,
    InMemoryJobRepository,
    JobService,
)


class FakeWebSocket:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[dict] = []
        self._fail = fail

    async def send(self, raw: str) -> None:
        if self._fail:
            import websockets
            raise websockets.ConnectionClosed(None, None)
        self.sent.append(json.loads(raw))


@pytest.fixture
def setup():
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
    yield gateway, registry
    log_repo.close()


async def test_send_cancel_returns_false_when_agent_missing(setup) -> None:
    gateway, _ = setup
    ok = await gateway.send_cancel("agent-1", "job_1", reason="user")
    assert ok is False


async def test_send_cancel_sends_message(setup) -> None:
    gateway, registry = setup
    ws = FakeWebSocket()
    registry.register("agent-1", ws)

    ok = await gateway.send_cancel("agent-1", "job_1", reason="user")

    assert ok is True
    assert ws.sent == [{"type": "cancel", "job_id": "job_1", "reason": "user"}]


async def test_send_cancel_returns_false_on_closed_socket(setup) -> None:
    gateway, registry = setup
    registry.register("agent-1", FakeWebSocket(fail=True))

    ok = await gateway.send_cancel("agent-1", "job_1", reason="timeout")
    assert ok is False