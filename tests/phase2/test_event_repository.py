import pytest

from packages.server.event_repository import SQLiteEventRepository


@pytest.fixture
def repo() -> SQLiteEventRepository:
    r = SQLiteEventRepository(":memory:")
    yield r
    r.close()


@pytest.fixture
def tmp_db(tmp_path) -> str:
    return str(tmp_path / "jobs.db")


def test_append_and_list(repo: SQLiteEventRepository) -> None:
    repo.append("job_1", "state_change", {"from": "PENDING", "to": "DISPATCHED"})
    repo.append("job_1", "ack")
    repo.append("job_1", "result", {"exit_code": 0})

    events = repo.list_for_job("job_1")
    assert [e["eventType"] for e in events] == ["state_change", "ack", "result"]


def test_payload_roundtrip(repo: SQLiteEventRepository) -> None:
    repo.append("job_1", "state_change", {"from": "PENDING", "to": "DISPATCHED"})
    events = repo.list_for_job("job_1")
    assert events[0]["payload"] == {"from": "PENDING", "to": "DISPATCHED"}


def test_empty_payload(repo: SQLiteEventRepository) -> None:
    repo.append("job_1", "ack")
    events = repo.list_for_job("job_1")
    assert events[0]["payload"] == {}


def test_list_empty_for_unknown_job(repo: SQLiteEventRepository) -> None:
    assert repo.list_for_job("missing") == []


def test_events_isolated_per_job(repo: SQLiteEventRepository) -> None:
    repo.append("job_1", "ack")
    repo.append("job_2", "ack")
    repo.append("job_2", "result")

    assert len(repo.list_for_job("job_1")) == 1
    assert len(repo.list_for_job("job_2")) == 2


def test_events_survive_reopen(tmp_db: str) -> None:
    r1 = SQLiteEventRepository(tmp_db)
    r1.append("job_1", "state_change", {"from": "PENDING", "to": "DISPATCHED"})
    r1.close()

    r2 = SQLiteEventRepository(tmp_db)
    try:
        events = r2.list_for_job("job_1")
        assert events[0]["eventType"] == "state_change"
    finally:
        r2.close()