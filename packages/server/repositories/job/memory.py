from typing import Optional

from packages.server.domain import Job, now
from packages.server.repositories.job.base import JobRepository
from packages.shared.protocol import JobState


class InMemoryJobRepository(JobRepository):
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._idempotency: dict[str, str] = {}

    def add(self, job: Job) -> Job:
        if job.idempotency_key is not None:
            existing_id = self._idempotency.get(job.idempotency_key)
            if existing_id is not None:
                return self._jobs[existing_id]
            self._idempotency[job.idempotency_key] = job.job_id
        self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def get_by_idempotency_key(self, key: str) -> Optional[Job]:
        job_id = self._idempotency.get(key)
        return self._jobs.get(job_id) if job_id else None

    def list(
        self,
        agent_id: Optional[str] = None,
        state: Optional[JobState] = None,
    ) -> list[Job]:
        jobs = list(self._jobs.values())
        if agent_id:
            jobs = [j for j in jobs if j.agent_id == agent_id]
        if state:
            jobs = [j for j in jobs if j.state == state]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)

    def save(self, job: Job) -> Job:
        job.updated_at = now()
        self._jobs[job.job_id] = job
        return job

    def transition_if(
        self,
        job_id: str,
        expected: JobState,
        new_state: JobState,
    ) -> Optional[Job]:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        if job.state != expected:
            return job
        job.state = new_state
        job.updated_at = now()
        if new_state == JobState.RUNNING and job.started_at is None:
            job.started_at = job.updated_at
        if new_state.is_terminal:
            job.finished_at = job.updated_at
        return job

    def complete_if_running(
        self,
        job_id: str,
        new_state: JobState,
        exit_code: int,
        stdout: str,
        stderr: str,
        error: Optional[str],
    ) -> Optional[Job]:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        if job.state != JobState.RUNNING:
            return job
        job.exit_code = exit_code
        job.stdout = stdout
        job.stderr = stderr
        job.error = error
        job.state = new_state
        job.updated_at = now()
        job.finished_at = job.updated_at
        return job