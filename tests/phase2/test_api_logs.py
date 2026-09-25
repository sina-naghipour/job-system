import pytest
from fastapi.testclient import TestClient

from packages.server.api import build_app
from packages.server.gateway import AgentGateway
from packages.server.log_broker import LogBroker
from packages.server.log_repository import SQLiteLogRepository
from packages.server.store import (
    AgentRegistry,
    InMemoryJobRepository,
    JobService,
)


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
    client = TestClient(build_app(service, gateway, broker, log_repo))
    yield client, service, log_repo
    log_repo.close()


def test_logs_404_for_unknown_job(setup) -> None:
    client, _, _ = setup
    assert client.get("/jobs/job_missing/logs").status_code == 404


def test_logs_returns_persisted_chunks(setup) -> None:
    client, service, log_repo = setup
    job = service.submit("agent-1", "alpine", ["echo"], 1000)
    log_repo.append(job.job_id, "stdout", 1, "hello ")
    log_repo.append(job.job_id, "stdout", 2, "world\n")

    r = client.get(f"/jobs/{job.job_id}/logs")
    assert r.status_code == 200
    assert r.text == "hello world\n"


def test_logs_filter_by_stream(setup) -> None:
    client, service, log_repo = setup
    job = service.submit("agent-1", "alpine", ["echo"], 1000)
    log_repo.append(job.job_id, "stdout", 1, "out")
    log_repo.append(job.job_id, "stderr", 1, "err")

    r = client.get(f"/jobs/{job.job_id}/logs?stream=stdout")
    assert r.text == "out"

    r = client.get(f"/jobs/{job.job_id}/logs?stream=stderr")
    assert r.text == "err"


def test_logs_empty_body_when_no_logs(setup) -> None:
    client, service, _ = setup
    job = service.submit("agent-1", "alpine", ["echo"], 1000)

    r = client.get(f"/jobs/{job.job_id}/logs")
    assert r.status_code == 200
    assert r.text == ""


def test_logs_preserves_interleave_order(setup) -> None:
    client, service, log_repo = setup
    job = service.submit("agent-1", "alpine", ["echo"], 1000)
    log_repo.append(job.job_id, "stdout", 1, "a")
    log_repo.append(job.job_id, "stderr", 1, "b")
    log_repo.append(job.job_id, "stdout", 2, "c")

    r = client.get(f"/jobs/{job.job_id}/logs")
    assert r.text == "abc"