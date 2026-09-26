import pytest

from packages.server.repositories import SQLiteLogRepository


@pytest.fixture
def repo() -> SQLiteLogRepository:
    r = SQLiteLogRepository(":memory:")
    yield r
    r.close()


@pytest.fixture
def tmp_db(tmp_path) -> str:
    return str(tmp_path / "jobs.db")


def test_append_and_list(repo: SQLiteLogRepository) -> None:
    repo.append("job_1", "stdout", 1, "a")
    repo.append("job_1", "stdout", 2, "b")

    entries = repo.list_for_job("job_1")
    assert [e["chunk"] for e in entries] == ["a", "b"]


def test_list_filters_by_stream(repo: SQLiteLogRepository) -> None:
    repo.append("job_1", "stdout", 1, "out")
    repo.append("job_1", "stderr", 1, "err")

    stdout = repo.list_for_job("job_1", stream="stdout")
    assert [e["chunk"] for e in stdout] == ["out"]

    stderr = repo.list_for_job("job_1", stream="stderr")
    assert [e["chunk"] for e in stderr] == ["err"]


def test_list_preserves_write_order(repo: SQLiteLogRepository) -> None:
    repo.append("job_1", "stderr", 1, "e1")
    repo.append("job_1", "stdout", 1, "o1")
    repo.append("job_1", "stderr", 2, "e2")
    repo.append("job_1", "stdout", 2, "o2")

    entries = repo.list_for_job("job_1")
    assert [e["chunk"] for e in entries] == ["e1", "o1", "e2", "o2"]


def test_list_empty_for_unknown_job(repo: SQLiteLogRepository) -> None:
    assert repo.list_for_job("missing") == []


def test_entries_carry_stream_and_sequence(repo: SQLiteLogRepository) -> None:
    repo.append("job_1", "stdout", 7, "x")
    entries = repo.list_for_job("job_1")
    assert entries[0]["stream"] == "stdout"
    assert entries[0]["sequence"] == 7


def test_logs_survive_reopen(tmp_db: str) -> None:
    r1 = SQLiteLogRepository(tmp_db)
    r1.append("job_1", "stdout", 1, "hello")
    r1.append("job_1", "stderr", 1, "world")
    r1.close()

    r2 = SQLiteLogRepository(tmp_db)
    try:
        entries = r2.list_for_job("job_1")
        assert [e["chunk"] for e in entries] == ["hello", "world"]
    finally:
        r2.close()