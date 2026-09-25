from datetime import datetime, timedelta, timezone

import pytest

from packages.server.ack_watcher import AckWatcher
from packages.server.store import InMemoryJobRepository, JobService
from packages.shared.protocol import JobState


class FakeGateway:
    def __init__(self) -> None:
        self.dispatched: list[str] = []

    async def dispatch_pending(self, agent_id: str) -> None:
        self.dispatched.append(agent_id)


@pytest.fixture
def service() -> JobService:
    return JobService(InMemoryJobRepository())


def _dispatched_job(service: JobService, *, age_seconds: float, attempts: int = 1):
    job = service.submit("agent-1", "alpine", ["echo"], 1000)
    service.mark_dispatched_with_attempt(job.job_id)
    job = service.get(job.job_id)
    job.dispatch_attempts = attempts
    old = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    job.updated_at = old.isoformat()
    return job


async def test_no_ack_within_window_is_ignored(service: JobService) -> None:
    _dispatched_job(service, age_seconds=1)
    gateway = FakeGateway()
    watcher = AckWatcher(service, gateway, ack_timeout_seconds=5.0)

    await watcher._scan()

    assert gateway.dispatched == []


async def test_stale_dispatch_is_requeued(service: JobService) -> None:
    job = _dispatched_job(service, age_seconds=10, attempts=1)
    gateway = FakeGateway()
    watcher = AckWatcher(service, gateway, ack_timeout_seconds=5.0)

    await watcher._scan()

    assert service.get(job.job_id).state == JobState.PENDING
    assert gateway.dispatched == ["agent-1"]


async def test_max_attempts_marks_failed(service: JobService) -> None:
    job = _dispatched_job(service, age_seconds=10, attempts=3)
    gateway = FakeGateway()
    watcher = AckWatcher(
        service, gateway, ack_timeout_seconds=5.0, max_dispatch_attempts=3
    )

    await watcher._scan()

    fetched = service.get(job.job_id)
    assert fetched.state == JobState.FAILED
    assert "No ack" in fetched.error
    assert gateway.dispatched == []


async def test_running_job_is_not_touched(service: JobService) -> None:
    job = _dispatched_job(service, age_seconds=10)
    service.mark_running(job.job_id)
    gateway = FakeGateway()
    watcher = AckWatcher(service, gateway, ack_timeout_seconds=5.0)

    await watcher._scan()

    assert service.get(job.job_id).state == JobState.RUNNING
    assert gateway.dispatched == []