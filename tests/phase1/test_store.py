import time

from packages.shared.protocol import JobState
from packages.server.domain import Job
from packages.server.repositories import InMemoryJobRepository
from packages.server.services import JobService, AgentRegistry

# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

def test_repository_add_and_get(repository: InMemoryJobRepository) -> None:
    job = Job("job_1", "agent-1", "alpine", ["echo"], 1000)
    repository.add(job)
    assert repository.get("job_1") is job


def test_repository_get_unknown_returns_none(repository: InMemoryJobRepository) -> None:
    assert repository.get("missing") is None


def test_repository_add_idempotent_by_key(repository: InMemoryJobRepository) -> None:
    a = Job("job_a", "agent-1", "alpine", ["echo"], 1000, idempotency_key="k")
    b = Job("job_b", "agent-1", "alpine", ["echo"], 1000, idempotency_key="k")
    assert repository.add(a).job_id == "job_a"
    assert repository.add(b).job_id == "job_a"


def test_repository_add_without_key_stores_all(repository: InMemoryJobRepository) -> None:
    repository.add(Job("job_a", "agent-1", "alpine", ["echo"], 1000))
    repository.add(Job("job_b", "agent-1", "alpine", ["echo"], 1000))
    assert repository.get("job_a") is not None
    assert repository.get("job_b") is not None


def test_repository_get_by_idempotency_key(repository: InMemoryJobRepository) -> None:
    job = Job("job_1", "agent-1", "alpine", ["echo"], 1000, idempotency_key="k")
    repository.add(job)
    assert repository.get_by_idempotency_key("k") is job
    assert repository.get_by_idempotency_key("missing") is None


def test_repository_list_empty(repository: InMemoryJobRepository) -> None:
    assert repository.list() == []


def test_repository_list_filters_by_agent(repository: InMemoryJobRepository) -> None:
    repository.add(Job("job_a", "agent-1", "alpine", ["echo"], 1000))
    repository.add(Job("job_b", "agent-2", "alpine", ["echo"], 1000))
    assert [j.job_id for j in repository.list(agent_id="agent-1")] == ["job_a"]


def test_repository_list_filters_by_state(repository: InMemoryJobRepository) -> None:
    a = Job("job_a", "agent-1", "alpine", ["echo"], 1000)
    a.state = JobState.RUNNING
    repository.add(a)
    repository.add(Job("job_b", "agent-1", "alpine", ["echo"], 1000))
    assert [j.job_id for j in repository.list(state=JobState.RUNNING)] == ["job_a"]


def test_repository_list_sorted_newest_first(repository: InMemoryJobRepository) -> None:
    repository.add(Job("job_a", "agent-1", "alpine", ["echo"], 1000))
    time.sleep(0.001)
    repository.add(Job("job_b", "agent-1", "alpine", ["echo"], 1000))
    assert [j.job_id for j in repository.list()] == ["job_b", "job_a"]


def test_repository_save_updates_job(repository: InMemoryJobRepository) -> None:
    job = Job("job_1", "agent-1", "alpine", ["echo"], 1000)
    repository.add(job)
    job.stdout = "hello"
    repository.save(job)
    assert repository.get("job_1").stdout == "hello"


def test_transition_if_succeeds_when_state_matches(repository: InMemoryJobRepository) -> None:
    repository.add(Job("job_1", "agent-1", "alpine", ["echo"], 1000))
    result = repository.transition_if("job_1", JobState.PENDING, JobState.DISPATCHED)
    assert result.state == JobState.DISPATCHED


def test_transition_if_rejected_when_state_differs(repository: InMemoryJobRepository) -> None:
    repository.add(Job("job_1", "agent-1", "alpine", ["echo"], 1000))
    result = repository.transition_if("job_1", JobState.RUNNING, JobState.SUCCEEDED)
    assert result.state == JobState.PENDING  # unchanged


def test_transition_if_unknown_job(repository: InMemoryJobRepository) -> None:
    assert repository.transition_if("missing", JobState.PENDING, JobState.DISPATCHED) is None


def test_complete_if_running_requires_running(repository: InMemoryJobRepository) -> None:
    repository.add(Job("job_1", "agent-1", "alpine", ["echo"], 1000))
    # Job is PENDING, not RUNNING. Completion should not apply.
    result = repository.complete_if_running(
        "job_1", JobState.SUCCEEDED, 0, "out", "", None
    )
    assert result.state == JobState.PENDING


def test_complete_if_running_applies(repository: InMemoryJobRepository) -> None:
    job = Job("job_1", "agent-1", "alpine", ["echo"], 1000)
    job.state = JobState.RUNNING
    repository.add(job)
    result = repository.complete_if_running(
        "job_1", JobState.SUCCEEDED, 0, "out", "", None
    )
    assert result.state == JobState.SUCCEEDED
    assert result.stdout == "out"


# ---------------------------------------------------------------------------
# JobService
# ---------------------------------------------------------------------------

def test_submit_creates_pending_job(job_service: JobService) -> None:
    job = job_service.submit("agent-1", "alpine", ["echo"], 1000)
    assert job.state == JobState.PENDING
    assert job.job_id.startswith("job_")


def test_submit_with_metadata(job_service: JobService) -> None:
    job = job_service.submit("agent-1", "alpine", ["echo"], 1000, metadata={"u": "x"})
    assert job.metadata == {"u": "x"}


def test_submit_default_metadata_is_empty(job_service: JobService) -> None:
    job = job_service.submit("agent-1", "alpine", ["echo"], 1000)
    assert job.metadata == {}


def test_submit_idempotent(job_service: JobService) -> None:
    a = job_service.submit("agent-1", "alpine", ["echo"], 1000, idempotency_key="k")
    b = job_service.submit("agent-1", "alpine", ["echo"], 1000, idempotency_key="k")
    assert a.job_id == b.job_id


def test_submit_no_key_creates_distinct(job_service: JobService) -> None:
    a = job_service.submit("agent-1", "alpine", ["echo"], 1000)
    b = job_service.submit("agent-1", "alpine", ["echo"], 1000)
    assert a.job_id != b.job_id


def test_get_unknown_returns_none(job_service: JobService) -> None:
    assert job_service.get("missing") is None


def test_mark_dispatched(job_service: JobService) -> None:
    job = job_service.submit("agent-1", "alpine", ["echo"], 1000)
    assert job_service.mark_dispatched(job.job_id).state == JobState.DISPATCHED


def test_mark_dispatched_from_wrong_state_is_noop(job_service: JobService) -> None:
    job = job_service.submit("agent-1", "alpine", ["echo"], 1000)
    job_service.mark_dispatched(job.job_id)
    # Already DISPATCHED, not PENDING. Transition should not happen.
    result = job_service.mark_dispatched(job.job_id)
    assert result.state == JobState.DISPATCHED


def test_mark_running_sets_started_at(job_service: JobService) -> None:
    job = job_service.submit("agent-1", "alpine", ["echo"], 1000)
    job_service.mark_dispatched(job.job_id)
    updated = job_service.mark_running(job.job_id)
    assert updated.state == JobState.RUNNING
    assert updated.started_at is not None


def test_mark_running_from_pending_is_noop(job_service: JobService) -> None:
    job = job_service.submit("agent-1", "alpine", ["echo"], 1000)
    # Job is PENDING, not DISPATCHED. Cannot jump to RUNNING.
    result = job_service.mark_running(job.job_id)
    assert result.state == JobState.PENDING


def test_mark_succeeded(job_service: JobService) -> None:
    job = job_service.submit("agent-1", "alpine", ["echo"], 1000)
    job_service.mark_dispatched(job.job_id)
    job_service.mark_running(job.job_id)
    updated = job_service.mark_succeeded(job.job_id, 0, "ok", "")
    assert updated.state == JobState.SUCCEEDED
    assert updated.exit_code == 0
    assert updated.finished_at is not None


def test_mark_failed_with_error(job_service: JobService) -> None:
    job = job_service.submit("agent-1", "alpine", ["false"], 1000)
    job_service.mark_dispatched(job.job_id)
    job_service.mark_running(job.job_id)
    updated = job_service.mark_failed(job.job_id, 42, "", "boom", error="boom")
    assert updated.state == JobState.FAILED
    assert updated.exit_code == 42
    assert updated.error == "boom"


def test_mark_timed_out(job_service: JobService) -> None:
    job = job_service.submit("agent-1", "alpine", ["sleep"], 1000)
    job_service.mark_dispatched(job.job_id)
    job_service.mark_running(job.job_id)
    updated = job_service.mark_timed_out(job.job_id)
    assert updated.state == JobState.TIMED_OUT


def test_mark_cancelled_from_pending(job_service: JobService) -> None:
    job = job_service.submit("agent-1", "alpine", ["sleep"], 1000)
    assert job_service.mark_cancelled(job.job_id).state == JobState.CANCELLED


def test_mark_cancelled_from_running(job_service: JobService) -> None:
    job = job_service.submit("agent-1", "alpine", ["sleep"], 1000)
    job_service.mark_dispatched(job.job_id)
    job_service.mark_running(job.job_id)
    assert job_service.mark_cancelled(job.job_id).state == JobState.CANCELLED


def test_requeue(job_service: JobService) -> None:
    job = job_service.submit("agent-1", "alpine", ["echo"], 1000)
    job_service.mark_dispatched(job.job_id)
    assert job_service.requeue(job.job_id).state == JobState.PENDING


def test_late_result_ignored(job_service: JobService) -> None:
    job = job_service.submit("agent-1", "alpine", ["echo"], 1000)
    job_service.mark_dispatched(job.job_id)
    job_service.mark_running(job.job_id)
    job_service.mark_timed_out(job.job_id)
    # Late result arrives. Must not change the terminal state.
    late = job_service.mark_succeeded(job.job_id, 0, "ok", "")
    assert late.state == JobState.TIMED_OUT


def test_terminal_state_protected(job_service: JobService) -> None:
    job = job_service.submit("agent-1", "alpine", ["echo"], 1000)
    job_service.mark_dispatched(job.job_id)
    job_service.mark_running(job.job_id)
    job_service.mark_succeeded(job.job_id, 0, "", "")

    assert job_service.mark_failed(job.job_id, 1, "", "").state == JobState.SUCCEEDED
    assert job_service.mark_timed_out(job.job_id).state == JobState.SUCCEEDED
    assert job_service.mark_cancelled(job.job_id).state == JobState.SUCCEEDED
    assert job_service.requeue(job.job_id).state == JobState.SUCCEEDED


def test_transitions_on_unknown_return_none(job_service: JobService) -> None:
    assert job_service.mark_dispatched("x") is None
    assert job_service.mark_running("x") is None
    assert job_service.mark_succeeded("x", 0, "", "") is None
    assert job_service.mark_failed("x", 1, "", "") is None
    assert job_service.mark_timed_out("x") is None
    assert job_service.mark_cancelled("x") is None
    assert job_service.requeue("x") is None


def test_list_filters(job_service: JobService) -> None:
    a = job_service.submit("agent-1", "alpine", ["echo"], 1000)
    job_service.submit("agent-2", "alpine", ["echo"], 1000)
    job_service.mark_dispatched(a.job_id)
    assert len(job_service.list(agent_id="agent-1")) == 1
    assert len(job_service.list(state=JobState.DISPATCHED)) == 1


def test_to_dict_shape(job_service: JobService) -> None:
    job = job_service.submit("agent-1", "alpine", ["echo"], 1000)
    d = job.to_dict()
    expected = {
        "jobId", "agentId", "image", "command", "timeoutMs",
        "idempotencyKey", "metadata", "state", "exitCode", "error",
        "createdAt", "updatedAt", "startedAt", "finishedAt", "correlationId",
    }
    assert expected.issubset(d.keys())
    assert d["state"] == "PENDING"


def test_to_result_shape(job_service: JobService) -> None:
    job = job_service.submit("agent-1", "alpine", ["echo"], 1000)
    assert set(job.to_result().keys()) == {
        "jobId", "state", "exitCode", "error", "stdout", "stderr"
    }


# ---------------------------------------------------------------------------
# AgentRegistry
# ---------------------------------------------------------------------------

def test_registry_register_and_get(agent_registry: AgentRegistry) -> None:
    ws = object()
    agent_registry.register("agent-1", ws)
    assert agent_registry.is_online("agent-1")
    assert agent_registry.get("agent-1").ws is ws


def test_registry_unregister(agent_registry: AgentRegistry) -> None:
    agent_registry.register("agent-1", object())
    agent_registry.unregister("agent-1")
    assert not agent_registry.is_online("agent-1")


def test_registry_unregister_unknown_is_noop(agent_registry: AgentRegistry) -> None:
    agent_registry.unregister("missing")


def test_registry_all(agent_registry: AgentRegistry) -> None:
    agent_registry.register("a", object())
    agent_registry.register("b", object())
    assert len(agent_registry.all()) == 2


def test_registry_get_unknown(agent_registry: AgentRegistry) -> None:
    assert agent_registry.get("missing") is None