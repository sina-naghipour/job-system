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


class RecordingGateway(AgentGateway):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.cancels: list[tuple[str, str, str]] = []

    async def send_cancel(self, agent_id: str, job_id: str, reason: str) -> bool:
        self.cancels.append((agent_id, job_id, reason))
        return True


@pytest.fixture
def setup():
    service = JobService(InMemoryJobRepository())
    registry = AgentRegistry()
    broker = LogBroker()
    log_repo = SQLiteLogRepository(":memory:")
    gateway = RecordingGateway(
        job_service=service,
        agent_registry=registry,
        log_broker=broker,
        log_repository=log_repo,
        host="127.0.0.1",
        port=0,
    )
    client = TestClient(build_app(service, gateway, broker, log_repo))
    yield client, service, gateway
    log_repo.close()


def _submit(client: TestClient) -> str:
    r = client.post("/jobs", json={
        "agentId": "agent-1",
        "image": "alpine:latest",
        "command": ["sleep", "60"],
        "timeoutMs": 60_000,
    })
    return r.json()["jobId"]


def test_cancel_unknown_job_returns_404(setup) -> None:
    client, _, _ = setup
    r = client.post("/jobs/job_missing/cancel")
    assert r.status_code == 404


def test_cancel_terminal_job_returns_409(setup) -> None:
    client, service, _ = setup
    job_id = _submit(client)
    service.mark_dispatched(job_id)
    service.mark_running(job_id)
    service.mark_succeeded(job_id, 0, "", "")

    r = client.post(f"/jobs/{job_id}/cancel")
    assert r.status_code == 409


def test_cancel_pending_job_succeeds(setup) -> None:
    client, service, gateway = setup
    job_id = _submit(client)

    r = client.post(f"/jobs/{job_id}/cancel")
    assert r.status_code == 202
    assert r.json() == {"jobId": job_id, "state": "CANCELLED"}
    assert service.get(job_id).state.value == "CANCELLED"
    assert gateway.cancels == [("agent-1", job_id, "user")]


def test_cancel_running_job_succeeds(setup) -> None:
    client, service, gateway = setup
    job_id = _submit(client)
    service.mark_dispatched(job_id)
    service.mark_running(job_id)

    r = client.post(f"/jobs/{job_id}/cancel")
    assert r.status_code == 202
    assert service.get(job_id).state.value == "CANCELLED"
    assert gateway.cancels == [("agent-1", job_id, "user")]


def test_cancel_sends_to_correct_agent(setup) -> None:
    client, _, gateway = setup
    r = client.post("/jobs", json={
        "agentId": "agent-7",
        "image": "alpine:latest",
        "command": ["sleep", "60"],
        "timeoutMs": 60_000,
    })
    job_id = r.json()["jobId"]

    client.post(f"/jobs/{job_id}/cancel")
    assert gateway.cancels == [("agent-7", job_id, "user")]