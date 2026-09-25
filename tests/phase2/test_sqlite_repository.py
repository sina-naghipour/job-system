import pytest

from packages.server.repositories import SQLiteJobRepository
from packages.server.domain import Job
from packages.shared.protocol import JobState


@pytest.fixture
def repo() -> SQLiteJobRepository:
    r = SQLiteJobRepository(":memory:")
    yield r
    r.close()


@pytest.fixture
def tmp_db(tmp_path) -> str:
    return str(tmp_path / "jobs.db")


def test_add_and_get(repo: SQLiteJobRepository) -> None:
    repo.add(Job("job_1", "agent-1", "alpine", ["echo"], 1000))
    fetched = repo.get("job_1")
    assert fetched is not None
    assert fetched.job_id == "job_1"
    assert fetched.command == ["echo"]


def test_get_unknown_returns_none(repo: SQLiteJobRepository) -> None:
    assert repo.get("missing") is None


def test_add_idempotent_by_key(repo: SQLiteJobRepository) -> None:
    a = Job("job_a", "agent-1", "alpine", ["echo"], 1000, idempotency_key="k")
    b = Job("job_b", "agent-1", "alpine", ["echo"], 1000, idempotency_key="k")
    assert repo.add(a).job_id == "job_a"
    assert repo.add(b).job_id == "job_a"
    assert repo.get("job_b") is None


def test_get_by_idempotency_key(repo: SQLiteJobRepository) -> None:
    repo.add(Job("job_1", "agent-1", "alpine", ["echo"], 1000, idempotency_key="k"))
    assert repo.get_by_idempotency_key("k").job_id == "job_1"
    assert repo.get_by_idempotency_key("missing") is None


def test_list_filters_by_agent(repo: SQLiteJobRepository) -> None:
    repo.add(Job("job_a", "agent-1", "alpine", ["echo"], 1000))
    repo.add(Job("job_b", "agent-2", "alpine", ["echo"], 1000))
    assert [j.job_id for j in repo.list(agent_id="agent-1")] == ["job_a"]


def test_list_filters_by_state(repo: SQLiteJobRepository) -> None:
    a = Job("job_a", "agent-1", "alpine", ["echo"], 1000)
    a.state = JobState.RUNNING
    repo.add(a)
    repo.add(Job("job_b", "agent-1", "alpine", ["echo"], 1000))
    assert [j.job_id for j in repo.list(state=JobState.RUNNING)] == ["job_a"]


def test_transition_if_succeeds(repo: SQLiteJobRepository) -> None:
    repo.add(Job("job_1", "agent-1", "alpine", ["echo"], 1000))
    result = repo.transition_if("job_1", JobState.PENDING, JobState.DISPATCHED)
    assert result.state == JobState.DISPATCHED


def test_transition_if_rejected_when_state_differs(repo: SQLiteJobRepository) -> None:
    repo.add(Job("job_1", "agent-1", "alpine", ["echo"], 1000))
    result = repo.transition_if("job_1", JobState.RUNNING, JobState.SUCCEEDED)
    assert result.state == JobState.PENDING


def test_transition_if_unknown_job(repo: SQLiteJobRepository) -> None:
    assert repo.transition_if("missing", JobState.PENDING, JobState.DISPATCHED) is None


def test_transition_sets_started_at_only_on_running(repo: SQLiteJobRepository) -> None:
    repo.add(Job("job_1", "agent-1", "alpine", ["echo"], 1000))
    repo.transition_if("job_1", JobState.PENDING, JobState.DISPATCHED)
    assert repo.get("job_1").started_at is None

    repo.transition_if("job_1", JobState.DISPATCHED, JobState.RUNNING)
    assert repo.get("job_1").started_at is not None


def test_complete_if_running(repo: SQLiteJobRepository) -> None:
    job = Job("job_1", "agent-1", "alpine", ["echo"], 1000)
    job.state = JobState.RUNNING
    repo.add(job)
    result = repo.complete_if_running("job_1", JobState.SUCCEEDED, 0, "out", "", None)
    assert result.state == JobState.SUCCEEDED
    assert result.exit_code == 0
    assert result.stdout == "out"
    assert result.finished_at is not None


def test_complete_if_running_rejected_when_not_running(repo: SQLiteJobRepository) -> None:
    repo.add(Job("job_1", "agent-1", "alpine", ["echo"], 1000))
    result = repo.complete_if_running("job_1", JobState.SUCCEEDED, 0, "out", "", None)
    assert result.state == JobState.PENDING


def test_metadata_roundtrip(repo: SQLiteJobRepository) -> None:
    repo.add(Job("job_1", "agent-1", "alpine", ["echo"], 1000, metadata={"user": "42"}))
    assert repo.get("job_1").metadata == {"user": "42"}


def test_command_roundtrip(repo: SQLiteJobRepository) -> None:
    repo.add(Job("job_1", "agent-1", "alpine", ["sh", "-c", "echo hi"], 1000))
    assert repo.get("job_1").command == ["sh", "-c", "echo hi"]


def test_jobs_survive_reopen(tmp_db: str) -> None:
    r1 = SQLiteJobRepository(tmp_db)
    r1.add(Job("job_1", "agent-1", "alpine", ["echo"], 1000))
    r1.close()

    r2 = SQLiteJobRepository(tmp_db)
    try:
        fetched = r2.get("job_1")
        assert fetched is not None
        assert fetched.command == ["echo"]
    finally:
        r2.close()


def test_idempotency_survives_reopen(tmp_db: str) -> None:
    r1 = SQLiteJobRepository(tmp_db)
    r1.add(Job("job_1", "agent-1", "alpine", ["echo"], 1000, idempotency_key="k"))
    r1.close()

    r2 = SQLiteJobRepository(tmp_db)
    try:
        duplicate = r2.add(
            Job("job_2", "agent-1", "alpine", ["echo"], 1000, idempotency_key="k")
        )
        assert duplicate.job_id == "job_1"
    finally:
        r2.close()


def test_state_survives_reopen(tmp_db: str) -> None:
    r1 = SQLiteJobRepository(tmp_db)
    r1.add(Job("job_1", "agent-1", "alpine", ["echo"], 1000))
    r1.transition_if("job_1", JobState.PENDING, JobState.DISPATCHED)
    r1.transition_if("job_1", JobState.DISPATCHED, JobState.RUNNING)
    r1.close()

    r2 = SQLiteJobRepository(tmp_db)
    try:
        fetched = r2.get("job_1")
        assert fetched.state == JobState.RUNNING
        assert fetched.started_at is not None
    finally:
        r2.close()