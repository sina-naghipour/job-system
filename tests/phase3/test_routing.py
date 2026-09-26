import json

import pytest

from packages.server.gateway import AgentGateway
from packages.server.repositories import (
    InMemoryJobRepository,
    SQLiteEventRepository,
    SQLiteLogRepository,
)
from packages.server.services import AgentRegistry, JobService, LogBroker
from packages.shared.protocol import JobState


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))


@pytest.fixture
def setup():
    service = JobService(InMemoryJobRepository())
    registry = AgentRegistry()
    broker = LogBroker()
    log_repo = SQLiteLogRepository(":memory:")
    event_repo = SQLiteEventRepository(":memory:")
    gateway = AgentGateway(
        job_service=service,
        agent_registry=registry,
        log_broker=broker,
        log_repository=log_repo,
        event_repository=event_repo,
        host="127.0.0.1",
        port=0,
    )
    try:
        yield service, gateway, registry
    finally:
        log_repo.close()
        event_repo.close()


async def test_job_routes_only_to_target_agent(setup) -> None:
    service, gateway, registry = setup

    ws1 = FakeWebSocket()
    ws2 = FakeWebSocket()
    registry.register("agent-1", ws1)
    registry.register("agent-2", ws2)

    job = service.submit("agent-1", "alpine", ["echo", "hi"], 1000)
    await gateway.dispatch_pending("agent-1")

    # Only the target received the job.
    assert [m["job_id"] for m in ws1.sent] == [job.job_id]
    assert ws2.sent == []


async def test_two_agents_each_get_their_own_jobs(setup) -> None:
    service, gateway, registry = setup

    ws1 = FakeWebSocket()
    ws2 = FakeWebSocket()
    registry.register("agent-1", ws1)
    registry.register("agent-2", ws2)

    job_a = service.submit("agent-1", "alpine", ["echo", "a"], 1000)
    job_b = service.submit("agent-2", "alpine", ["echo", "b"], 1000)

    await gateway.dispatch_pending("agent-1")
    await gateway.dispatch_pending("agent-2")

    # Each agent got exactly its own job. An agent is busy until it
    # reports a result, so the gateway sends it only one at a time.
    assert len(ws1.sent) == 1
    assert len(ws2.sent) == 1
    assert ws1.sent[0]["job_id"] == job_a.job_id
    assert ws2.sent[0]["job_id"] == job_b.job_id


async def test_job_for_unregistered_agent_stays_pending(setup) -> None:
    service, gateway, _ = setup

    job = service.submit("agent-3", "alpine", ["echo", "hi"], 1000)
    await gateway.dispatch_pending("agent-3")

    fetched = service.get(job.job_id)
    assert fetched.state == JobState.PENDING
    assert fetched.dispatch_attempts == 0


async def test_job_dispatches_when_target_agent_later_registers(setup) -> None:
    service, gateway, _ = setup

    # Agent is offline at submit time.
    job = service.submit("agent-2", "alpine", ["echo", "hi"], 1000)
    assert service.get(job.job_id).state == JobState.PENDING

    # Agent connects later.
    ws = FakeWebSocket()
    await gateway._dispatch(
        ws, {"type": "register", "agent_id": "agent-2"}, None
    )

    # Registering flushes the pending queue for that agent.
    assert [m["job_id"] for m in ws.sent] == [job.job_id]
    assert service.get(job.job_id).state == JobState.DISPATCHED