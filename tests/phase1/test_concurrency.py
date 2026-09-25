import asyncio

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
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, raw: str) -> None:
        await asyncio.sleep(0)
        import json
        self.sent.append(json.loads(raw))


@pytest.fixture
def setup() -> tuple[JobService, AgentGateway, AgentRegistry]:
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
    yield service, gateway, registry
    log_repo.close()


async def test_concurrent_dispatch_sends_once(setup) -> None:
    service, gateway, registry = setup
    job = service.submit("a1", "alpine", ["echo"], 1000)
    ws = FakeWebSocket()
    registry.register("a1", ws)

    await asyncio.gather(*[gateway.dispatch_pending("a1") for _ in range(20)])

    sent_ids = [m["job_id"] for m in ws.sent]
    assert sent_ids.count(job.job_id) == 1


async def test_concurrent_idempotent_submit(setup) -> None:
    service, _, _ = setup

    async def submit() -> str:
        return service.submit(
            "a1", "alpine", ["echo"], 1000, idempotency_key="same"
        ).job_id

    ids = await asyncio.gather(*[submit() for _ in range(20)])
    assert len(set(ids)) == 1


async def test_concurrent_transitions_only_one_wins(setup) -> None:
    service, _, _ = setup
    job = service.submit("a1", "alpine", ["echo"], 1000)

    await asyncio.gather(*[
        asyncio.to_thread(service.mark_dispatched, job.job_id)
        for _ in range(20)
    ])
    final = service.get(job.job_id)
    from packages.shared.protocol import JobState
    assert final.state == JobState.DISPATCHED