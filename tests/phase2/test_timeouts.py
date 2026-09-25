from datetime import datetime, timedelta, timezone

import pytest

from packages.server.store import (
    InMemoryJobRepository,
    Job,
    JobService,
)
from packages.server.timeouts import TimeoutWatcher
from packages.shared.protocol import JobState


class FakeGateway:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def send_cancel(self, agent_id: str, job_id: str, reason: str) -> bool:
        self.sent.append((agent_id, job_id, reason))
        return True


class FakeGatewayOffline:
    async def send_cancel(self, agent_id: str, job_id: str, reason: str) -> bool:
        return False


@pytest.fixture
def service() -> JobService:
    return JobService(InMemoryJobRepository())


def _running_job(
    service: JobService,
    *,
    age_seconds: float,
    timeout_ms: int,
) -> Job:
    """Create a Job and move it to RUNNING with a started_at in the past."""
    job = service.submit("agent-1", "alpine", ["sleep"], timeout_ms)
    service.mark_dispatched(job.job_id)
    service.mark_running(job.job_id)
    started = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    job.started_at = started.isoformat()
    service._repository.save(job)
    return job


async def test_no_timeout_when_within_budget(service: JobService) -> None:
    job = _running_job(service, age_seconds=1, timeout_ms=30_000)
    gateway = FakeGateway()
    watcher = TimeoutWatcher(service, gateway)

    await watcher._scan()

    assert gateway.sent == []
    assert service.get(job.job_id).state == JobState.RUNNING


async def test_timeout_fires_when_exceeded(service: JobService) -> None:
    job = _running_job(service, age_seconds=5, timeout_ms=1_000)
    gateway = FakeGateway()
    watcher = TimeoutWatcher(service, gateway)

    await watcher._scan()

    assert gateway.sent == [("agent-1", job.job_id, "timeout")]
    assert service.get(job.job_id).state == JobState.TIMED_OUT


async def test_timeout_fires_even_if_agent_offline(service: JobService) -> None:
    job = _running_job(service, age_seconds=5, timeout_ms=1_000)
    watcher = TimeoutWatcher(service, FakeGatewayOffline())

    await watcher._scan()

    assert service.get(job.job_id).state == JobState.TIMED_OUT


async def test_pending_jobs_are_ignored(service: JobService) -> None:
    job = service.submit("agent-1", "alpine", ["sleep"], 1_000)
    gateway = FakeGateway()
    watcher = TimeoutWatcher(service, gateway)

    await watcher._scan()

    assert gateway.sent == []
    assert service.get(job.job_id).state == JobState.PENDING


async def test_terminal_jobs_are_ignored(service: JobService) -> None:
    job = service.submit("agent-1", "alpine", ["echo"], 1_000)
    service.mark_dispatched(job.job_id)
    service.mark_running(job.job_id)
    service.mark_succeeded(job.job_id, 0, "", "")

    gateway = FakeGateway()
    watcher = TimeoutWatcher(service, gateway)

    await watcher._scan()

    assert gateway.sent == []


async def test_running_without_started_at_is_ignored(service: JobService) -> None:
    job = service.submit("agent-1", "alpine", ["sleep"], 1_000)
    service.mark_dispatched(job.job_id)
    service.mark_running(job.job_id)
    # Force started_at to None.
    job = service.get(job.job_id)
    job.started_at = None
    service._repository.save(job)

    gateway = FakeGateway()
    watcher = TimeoutWatcher(service, gateway)

    await watcher._scan()

    assert gateway.sent == []


async def test_multiple_jobs_each_fire_once(service: JobService) -> None:
    a = _running_job(service, age_seconds=5, timeout_ms=1_000)
    b = _running_job(service, age_seconds=5, timeout_ms=1_000)
    gateway = FakeGateway()
    watcher = TimeoutWatcher(service, gateway)

    await watcher._scan()

    sent_ids = {job_id for _, job_id, _ in gateway.sent}
    assert sent_ids == {a.job_id, b.job_id}
    assert service.get(a.job_id).state == JobState.TIMED_OUT
    assert service.get(b.job_id).state == JobState.TIMED_OUT


async def test_second_scan_does_not_refire(service: JobService) -> None:
    job = _running_job(service, age_seconds=5, timeout_ms=1_000)
    gateway = FakeGateway()
    watcher = TimeoutWatcher(service, gateway)

    await watcher._scan()
    await watcher._scan()

    # Only the first scan should have sent a cancel.
    assert len(gateway.sent) == 1
    assert gateway.sent[0][1] == job.job_id