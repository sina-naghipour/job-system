import pytest
from fastapi.testclient import TestClient

from packages.server.api import build_app
from packages.server.gateway import AgentGateway
from packages.server.log_broker import LogBroker
from packages.server.repositories import InMemoryJobRepository
from packages.server.store import AgentRegistry, JobService

from packages.server.repositories import SQLiteLogRepository, SQLiteEventRepository

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
    client = TestClient(build_app(service, gateway, broker, log_repo, event_repo))
    yield client, service, broker
    log_repo.close()
    event_repo.close()


def test_live_logs_404_for_unknown_job(setup) -> None:
    client, _, _ = setup
    r = client.get("/jobs/job_missing/logs/live")
    assert r.status_code == 404


def test_live_logs_replays_history_and_ends(setup) -> None:
    client, service, broker = setup
    job = service.submit("agent-1", "alpine", ["echo"], 1000)
    service.mark_dispatched(job.job_id)
    service.mark_running(job.job_id)

    broker.publish(job.job_id, "stdout", "hello\n")
    broker.publish(job.job_id, "stderr", "oops\n")
    service.mark_succeeded(job.job_id, 0, "hello\n", "oops\n")

    with client.stream("GET", f"/jobs/{job.job_id}/logs/live") as r:
        assert r.status_code == 200
        body = "".join(r.iter_text())

    assert "event: log" in body
    assert "event: end" in body
    assert '"chunk": "hello\\n"' in body
    assert '"stream": "stderr"' in body


def test_live_logs_streams_new_chunks(setup) -> None:
    client, service, broker = setup
    job = service.submit("agent-1", "alpine", ["echo"], 1000)
    service.mark_dispatched(job.job_id)
    service.mark_running(job.job_id)
    service.mark_succeeded(job.job_id, 0, "", "")

    with client.stream("GET", f"/jobs/{job.job_id}/logs/live") as r:
        body = "".join(r.iter_text())

    assert "event: end" in body
    assert "event: log" not in body