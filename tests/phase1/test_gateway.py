import json

import pytest

from packages.shared.protocol import JobState
from packages.server.gateway import AgentGateway
from packages.server.log_broker import LogBroker
from packages.server.repositories import InMemoryJobRepository
from packages.server.store import AgentRegistry, JobService

from packages.server.repositories import SQLiteEventRepository, SQLiteLogRepository

class FakeWebSocket:
    def __init__(self, fail_on_send: bool = False) -> None:
        self.sent: list[dict] = []
        self._fail = fail_on_send

    async def send(self, raw: str) -> None:
        if self._fail:
            import websockets
            raise websockets.ConnectionClosed(None, None)
        self.sent.append(json.loads(raw))


@pytest.fixture
def setup() -> tuple[JobService, AgentGateway, AgentRegistry]:
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
    yield service, gateway, registry
    log_repo.close()
    event_repo.close()


def _advance_to_running(service: JobService, job_id: str) -> None:
    service.mark_dispatched(job_id)
    service.mark_running(job_id)


async def test_register(setup) -> None:
    _, gateway, registry = setup
    await gateway._dispatch(FakeWebSocket(), {"type": "register", "agent_id": "a1"}, None)
    assert registry.is_online("a1")


async def test_register_dispatches_pending(setup) -> None:
    service, gateway, _ = setup
    job = service.submit("a1", "alpine", ["echo"], 1000)
    ws = FakeWebSocket()
    await gateway._dispatch(ws, {"type": "register", "agent_id": "a1"}, None)
    assert ws.sent[0]["job_id"] == job.job_id
    assert service.get(job.job_id).state == JobState.DISPATCHED


async def test_ack_no_op(setup) -> None:
    service, gateway, _ = setup
    job = service.submit("a1", "alpine", ["echo"], 1000)
    result = await gateway._dispatch(
        FakeWebSocket(), {"type": "ack", "job_id": job.job_id}, "a1"
    )
    assert result == "a1"
    assert service.get(job.job_id).state == JobState.PENDING


async def test_started_marks_running(setup) -> None:
    service, gateway, _ = setup
    job = service.submit("a1", "alpine", ["echo"], 1000)
    service.mark_dispatched(job.job_id)
    await gateway._dispatch(
        FakeWebSocket(), {"type": "started", "job_id": job.job_id}, "a1"
    )
    assert service.get(job.job_id).state == JobState.RUNNING


async def test_result_success(setup) -> None:
    service, gateway, _ = setup
    job = service.submit("a1", "alpine", ["echo"], 1000)
    _advance_to_running(service, job.job_id)
    await gateway._dispatch(FakeWebSocket(), {
        "type": "result", "job_id": job.job_id,
        "exit_code": 0, "stdout": "hi", "stderr": "", "error": None,
    }, "a1")
    fetched = service.get(job.job_id)
    assert fetched.state == JobState.SUCCEEDED
    assert fetched.stdout == "hi"


async def test_result_failure(setup) -> None:
    service, gateway, _ = setup
    job = service.submit("a1", "alpine", ["false"], 1000)
    _advance_to_running(service, job.job_id)
    await gateway._dispatch(FakeWebSocket(), {
        "type": "result", "job_id": job.job_id,
        "exit_code": 42, "stdout": "", "stderr": "boom", "error": None,
    }, "a1")
    fetched = service.get(job.job_id)
    assert fetched.state == JobState.FAILED
    assert fetched.exit_code == 42


async def test_result_with_infra_error(setup) -> None:
    service, gateway, _ = setup
    job = service.submit("a1", "alpine", ["echo"], 1000)
    _advance_to_running(service, job.job_id)
    await gateway._dispatch(FakeWebSocket(), {
        "type": "result", "job_id": job.job_id,
        "exit_code": 1, "stdout": "", "stderr": "",
        "error": "docker daemon unreachable",
    }, "a1")
    fetched = service.get(job.job_id)
    assert fetched.state == JobState.FAILED
    assert fetched.error == "docker daemon unreachable"


async def test_log_message_publishes_to_broker(setup) -> None:
    service, gateway, _ = setup
    job = service.submit("a1", "alpine", ["echo"], 1000)

    await gateway._dispatch(FakeWebSocket(), {
        "type": "log",
        "job_id": job.job_id,
        "stream": "stdout",
        "sequence": 1,
        "chunk": "hello",
    }, "a1")

    history = gateway._log_broker.history(job.job_id)
    assert len(history) == 1
    assert history[0].chunk == "hello"
    assert history[0].stream == "stdout"


async def test_log_message_persists_to_repository(setup) -> None:
    service, gateway, _ = setup
    job = service.submit("a1", "alpine", ["echo"], 1000)

    await gateway._dispatch(FakeWebSocket(), {
        "type": "log",
        "job_id": job.job_id,
        "stream": "stdout",
        "sequence": 1,
        "chunk": "persisted",
    }, "a1")

    entries = gateway._log_repository.list_for_job(job.job_id)
    assert len(entries) == 1
    assert entries[0]["chunk"] == "persisted"


async def test_ack_records_event(setup) -> None:
    service, gateway, _ = setup
    job = service.submit("a1", "alpine", ["echo"], 1000)

    await gateway._dispatch(
        FakeWebSocket(), {"type": "ack", "job_id": job.job_id}, "a1"
    )

    events = gateway._event_repository.list_for_job(job.job_id)
    assert any(e["eventType"] == "ack" for e in events)


async def test_started_records_event(setup) -> None:
    service, gateway, _ = setup
    job = service.submit("a1", "alpine", ["echo"], 1000)
    service.mark_dispatched(job.job_id)

    await gateway._dispatch(
        FakeWebSocket(), {"type": "started", "job_id": job.job_id}, "a1"
    )

    events = gateway._event_repository.list_for_job(job.job_id)
    assert any(e["eventType"] == "started" for e in events)


async def test_result_records_event(setup) -> None:
    service, gateway, _ = setup
    job = service.submit("a1", "alpine", ["echo"], 1000)
    _advance_to_running(service, job.job_id)

    await gateway._dispatch(FakeWebSocket(), {
        "type": "result", "job_id": job.job_id,
        "exit_code": 0, "stdout": "", "stderr": "", "error": None,
    }, "a1")

    events = gateway._event_repository.list_for_job(job.job_id)
    assert any(e["eventType"] == "result" for e in events)


async def test_dispatched_records_event(setup) -> None:
    service, gateway, _ = setup
    job = service.submit("a1", "alpine", ["echo"], 1000)
    ws = FakeWebSocket()
    await gateway._dispatch(ws, {"type": "register", "agent_id": "a1"}, None)

    events = gateway._event_repository.list_for_job(job.job_id)
    dispatched = [e for e in events if e["eventType"] == "dispatched"]
    assert len(dispatched) == 1
    assert dispatched[0]["payload"]["attempt"] == 1


async def test_heartbeat_ignored(setup) -> None:
    _, gateway, _ = setup
    assert await gateway._dispatch(
        FakeWebSocket(), {"type": "heartbeat", "agent_id": "a1"}, "a1"
    ) == "a1"


async def test_unknown_type_ignored(setup) -> None:
    _, gateway, _ = setup
    assert await gateway._dispatch(FakeWebSocket(), {"type": "bogus"}, "a1") == "a1"


async def test_dispatch_pending_sends_all(setup) -> None:
    service, gateway, registry = setup
    a = service.submit("a1", "alpine", ["echo", "a"], 1000)
    b = service.submit("a1", "alpine", ["echo", "b"], 1000)
    ws = FakeWebSocket()
    registry.register("a1", ws)
    await gateway.dispatch_pending("a1")
    assert {m["job_id"] for m in ws.sent} == {a.job_id, b.job_id}


async def test_dispatch_pending_no_agent(setup) -> None:
    _, gateway, _ = setup
    await gateway.dispatch_pending("missing")


async def test_dispatch_pending_send_fails(setup) -> None:
    service, gateway, registry = setup
    service.submit("a1", "alpine", ["echo"], 1000)
    registry.register("a1", FakeWebSocket(fail_on_send=True))
    await gateway.dispatch_pending("a1")