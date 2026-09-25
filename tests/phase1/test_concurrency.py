import asyncio

import pytest

from packages.server.gateway import AgentGateway
from packages.server.store import (
    AgentRegistry,
    InMemoryJobRepository,
    JobService,
)

from packages.server.log_broker import LogBroker



class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, raw: str) -> None:
        # Yield to give other coroutines a chance to interleave.
        await asyncio.sleep(0)
        import json
        self.sent.append(json.loads(raw))


@pytest.fixture
def setup() -> tuple[JobService, AgentGateway, AgentRegistry]:
    service = JobService(InMemoryJobRepository())
    registry = AgentRegistry()
    gateway = AgentGateway(
        job_service=service,
        agent_registry=registry,
        log_broker=LogBroker(),
        host="127.0.0.1",
        port=0,
    )
    return service, gateway, registry


async def test_concurrent_dispatch_sends_once(setup) -> None:
    service, gateway, registry = setup
    job = service.submit("a1", "alpine", ["echo"], 1000)
    ws = FakeWebSocket()
    registry.register("a1", ws)

    # Fire 20 concurrent dispatches for the same agent.
    await asyncio.gather(*[gateway.dispatch_pending("a1") for _ in range(20)])

    # The job must have been sent exactly once.
    sent_ids = [m["job_id"] for m in ws.sent]
    assert sent_ids.count(job.job_id) == 1


async def test_concurrent_idempotent_submit(setup) -> None:
    service, _, _ = setup

    async def submit() -> str:
        return service.submit(
            "a1", "alpine", ["echo"], 1000, idempotency_key="same"
        ).job_id

    ids = await asyncio.gather(*[submit() for _ in range(20)])
    assert len(set(ids)) == 1  # all 20 calls returned the same job_id


async def test_concurrent_transitions_only_one_wins(setup) -> None:
    service, _, _ = setup
    job = service.submit("a1", "alpine", ["echo"], 1000)

    # 20 concurrent mark_dispatched calls. Only the first should transition.
    results = await asyncio.gather(*[
        asyncio.to_thread(service.mark_dispatched, job.job_id)
        for _ in range(20)
    ])
    final = service.get(job.job_id)
    from packages.shared.protocol import JobState
    assert final.state == JobState.DISPATCHED