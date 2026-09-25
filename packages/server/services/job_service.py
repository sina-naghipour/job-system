from typing import Optional

from packages.server.domain import Job, new_job_id, now
from packages.server.repositories.job import JobRepository
from packages.shared.protocol import JobState


class JobService:
    def __init__(self, repository: JobRepository) -> None:
        self._repository = repository

    def submit(
        self,
        agent_id: str,
        image: str,
        command: list[str],
        timeout_ms: int,
        idempotency_key: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> Job:
        job = Job(
            job_id=new_job_id(),
            agent_id=agent_id,
            image=image,
            command=command,
            timeout_ms=timeout_ms,
            idempotency_key=idempotency_key,
            metadata=metadata or {},
        )
        return self._repository.add(job)

    def get(self, job_id: str) -> Optional[Job]:
        return self._repository.get(job_id)

    def list(
        self,
        agent_id: Optional[str] = None,
        state: Optional[JobState] = None,
    ) -> list[Job]:
        return self._repository.list(agent_id=agent_id, state=state)

    def mark_dispatched(self, job_id: str) -> Optional[Job]:
        return self._repository.transition_if(
            job_id, JobState.PENDING, JobState.DISPATCHED
        )

    def mark_dispatched_with_attempt(self, job_id: str) -> Optional[Job]:
        job = self._repository.get(job_id)
        if job is None:
            return None
        if job.state != JobState.PENDING:
            return job
        job.state = JobState.DISPATCHED
        job.dispatch_attempts += 1
        job.updated_at = now()
        return self._repository.save(job)

    def mark_running(self, job_id: str) -> Optional[Job]:
        return self._repository.transition_if(
            job_id, JobState.DISPATCHED, JobState.RUNNING
        )

    def mark_succeeded(
        self, job_id: str, exit_code: int, stdout: str, stderr: str
    ) -> Optional[Job]:
        return self._repository.complete_if_running(
            job_id, JobState.SUCCEEDED, exit_code, stdout, stderr, error=None
        )

    def mark_failed(
        self,
        job_id: str,
        exit_code: int,
        stdout: str,
        stderr: str,
        error: Optional[str] = None,
    ) -> Optional[Job]:
        return self._repository.complete_if_running(
            job_id, JobState.FAILED, exit_code, stdout, stderr, error
        )

    def mark_timed_out(self, job_id: str) -> Optional[Job]:
        return self._repository.transition_if(
            job_id, JobState.RUNNING, JobState.TIMED_OUT
        )

    def mark_cancelled(self, job_id: str) -> Optional[Job]:
        job = self._repository.get(job_id)
        if job is None or job.state.is_terminal:
            return job
        return self._repository.transition_if(
            job_id, job.state, JobState.CANCELLED
        )

    def requeue(self, job_id: str) -> Optional[Job]:
        return self._repository.transition_if(
            job_id, JobState.DISPATCHED, JobState.PENDING
        )

    def fail_stale_dispatch(self, job_id: str, error: str) -> Optional[Job]:
        job = self._repository.get(job_id)
        if job is None or job.state.is_terminal:
            return job
        job.exit_code = 1
        job.error = error
        job.state = JobState.FAILED
        job.finished_at = now()
        return self._repository.save(job)