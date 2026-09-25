import pytest
from fastapi.testclient import TestClient

from packages.server.api import build_app
from packages.server.event_repository import SQLiteEventRepository
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
    yield client
    log_repo.close()
    event_repo.close()


@pytest.fixture
def client(setup) -> TestClient:
    return setup


def _payload(**overrides) -> dict:
    base = {
        "agentId": "agent-1",
        "image": "alpine:latest",
        "command": ["echo", "hi"],
        "timeoutMs": 1000,
    }
    base.update(overrides)
    return base


def test_submit_202_and_job_id(client: TestClient) -> None:
    r = client.post("/jobs", json=_payload())
    assert r.status_code == 202
    assert r.json()["jobId"].startswith("job_")


def test_submit_missing_agent_id_422(client: TestClient) -> None:
    p = _payload()
    del p["agentId"]
    assert client.post("/jobs", json=p).status_code == 422


def test_submit_empty_agent_id_422(client: TestClient) -> None:
    assert client.post("/jobs", json=_payload(agentId="")).status_code == 422


def test_submit_missing_image_422(client: TestClient) -> None:
    p = _payload()
    del p["image"]
    assert client.post("/jobs", json=p).status_code == 422


def test_submit_empty_command_422(client: TestClient) -> None:
    assert client.post("/jobs", json=_payload(command=[])).status_code == 422


def test_submit_non_positive_timeout_422(client: TestClient) -> None:
    assert client.post("/jobs", json=_payload(timeoutMs=0)).status_code == 422


def test_submit_default_timeout(client: TestClient) -> None:
    p = _payload()
    del p["timeoutMs"]
    assert client.post("/jobs", json=p).status_code == 202


def test_get_job(client: TestClient) -> None:
    job_id = client.post("/jobs", json=_payload()).json()["jobId"]
    r = client.get(f"/jobs/{job_id}")
    assert r.status_code == 200
    assert r.json()["jobId"] == job_id
    assert r.json()["state"] == "PENDING"


def test_get_job_404(client: TestClient) -> None:
    assert client.get("/jobs/job_missing").status_code == 404


def test_get_result_404(client: TestClient) -> None:
    assert client.get("/jobs/job_missing/result").status_code == 404


def test_get_result_shape(client: TestClient) -> None:
    job_id = client.post("/jobs", json=_payload()).json()["jobId"]
    body = client.get(f"/jobs/{job_id}/result").json()
    assert set(body.keys()) == {
        "jobId", "state", "exitCode", "error", "stdout", "stderr"
    }


def test_idempotent_submit(client: TestClient) -> None:
    p = _payload(idempotencyKey="k")
    a = client.post("/jobs", json=p).json()["jobId"]
    b = client.post("/jobs", json=p).json()["jobId"]
    assert a == b


def test_list_jobs(client: TestClient) -> None:
    for _ in range(3):
        client.post("/jobs", json=_payload())
    assert len(client.get("/jobs").json()["jobs"]) == 3


def test_list_filter_by_agent(client: TestClient) -> None:
    client.post("/jobs", json=_payload(agentId="a1"))
    client.post("/jobs", json=_payload(agentId="a2"))
    assert len(client.get("/jobs?agentId=a1").json()["jobs"]) == 1


def test_list_filter_by_state(client: TestClient) -> None:
    client.post("/jobs", json=_payload())
    assert len(client.get("/jobs?state=PENDING").json()["jobs"]) == 1
    assert client.get("/jobs?state=SUCCEEDED").json()["jobs"] == []