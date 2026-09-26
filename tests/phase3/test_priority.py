import pytest

from packages.server.domain import Job
from packages.server.repositories import InMemoryJobRepository
from packages.server.services import JobService
from packages.shared.protocol import JobState


@pytest.fixture
def service() -> JobService:
    return JobService(InMemoryJobRepository())


def test_job_defaults_to_priority_zero(service: JobService) -> None:
    job = service.submit("a1", "alpine", ["echo"], 1000)
    assert job.priority == 0


def test_job_carries_priority(service: JobService) -> None:
    job = service.submit("a1", "alpine", ["echo"], 1000, priority=2)
    assert job.priority == 2


def test_to_dict_includes_priority(service: JobService) -> None:
    job = service.submit("a1", "alpine", ["echo"], 1000, priority=1)
    assert job.to_dict()["priority"] == 1


def test_sorting_by_priority_then_created_at(service: JobService) -> None:
    # Submit in an order that would be wrong for FIFO.
    batch = service.submit("a1", "alpine", ["batch"], 1000, priority=2)
    normal = service.submit("a1", "alpine", ["normal"], 1000, priority=1)
    interactive = service.submit("a1", "alpine", ["interactive"], 1000, priority=0)

    pending = service.list(agent_id="a1", state=JobState.PENDING)
    ordered = sorted(pending, key=lambda j: (j.priority, j.created_at))

    assert [j.job_id for j in ordered] == [
        interactive.job_id,
        normal.job_id,
        batch.job_id,
    ]


def test_same_priority_is_fifo(service: JobService) -> None:
    first = service.submit("a1", "alpine", ["one"], 1000, priority=1)
    second = service.submit("a1", "alpine", ["two"], 1000, priority=1)
    third = service.submit("a1", "alpine", ["three"], 1000, priority=1)

    pending = service.list(agent_id="a1", state=JobState.PENDING)
    ordered = sorted(pending, key=lambda j: (j.priority, j.created_at))

    assert [j.job_id for j in ordered] == [
        first.job_id,
        second.job_id,
        third.job_id,
    ]

async def test_dispatch_picks_highest_priority_when_agent_busy() -> None:
    import asyncio
    import json
    from packages.server.domain import AgentConnection
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

    service = JobService(InMemoryJobRepository())
    registry = AgentRegistry()
    gateway = AgentGateway(
        job_service=service,
        agent_registry=registry,
        log_broker=LogBroker(),
        log_repository=SQLiteLogRepository(":memory:"),
        event_repository=SQLiteEventRepository(":memory:"),
        host="127.0.0.1",
        port=0,
    )

    ws = FakeWebSocket()
    registry.register("a1", ws)

    # Submit three jobs in the "wrong" order for FIFO.
    batch = service.submit("a1", "alpine", ["batch"], 1000, priority=2)
    normal = service.submit("a1", "alpine", ["normal"], 1000, priority=1)
    interactive = service.submit("a1", "alpine", ["interactive"], 1000, priority=0)

    await gateway.dispatch_pending("a1")

    # Only one job should have been sent, and it should be the interactive one.
    assert len(ws.sent) == 1
    assert ws.sent[0]["job_id"] == interactive.job_id

    # The other two remain PENDING.
    assert service.get(batch.job_id).state == JobState.PENDING
    assert service.get(normal.job_id).state == JobState.PENDING
    assert service.get(interactive.job_id).state == JobState.DISPATCHED