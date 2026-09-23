import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from packages.shared.protocol import JobState


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_job_id() -> str:
    return f"job_{uuid.uuid4().hex[:12]}"


@dataclass
class Job:
    job_id: str
    agent_id: str
    image: str
    command: list[str]
    timeout_ms: int
    idempotency_key: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    state: JobState = JobState.PENDING
    exit_code: Optional[int] = None
    error: Optional[str] = None
    stdout: str = ""
    stderr: str = ""
    created_at: str = field(default_factory=now)
    updated_at: str = field(default_factory=now)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    correlation_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_dict(self) -> dict:
        return {
            "jobId": self.job_id,
            "agentId": self.agent_id,
            "image": self.image,
            "command": self.command,
            "timeoutMs": self.timeout_ms,
            "idempotencyKey": self.idempotency_key,
            "metadata": self.metadata,
            "state": self.state.value,
            "exitCode": self.exit_code,
            "error": self.error,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "correlationId": self.correlation_id,
        }

    def to_result(self) -> dict:
        return {
            "jobId": self.job_id,
            "state": self.state.value,
            "exitCode": self.exit_code,
            "error": self.error,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


@dataclass
class AgentConnection:
    agent_id: str
    ws: object
    connected_at: str = field(default_factory=now)


class JobRepository(ABC):
    @abstractmethod
    def add(self, job: Job) -> Job: ...

    @abstractmethod
    def get(self, job_id: str) -> Optional[Job]: ...

    @abstractmethod
    def get_by_idempotency_key(self, key: str) -> Optional[Job]: ...

    @abstractmethod
    def list(
        self,
        agent_id: Optional[str] = None,
        state: Optional[JobState] = None,
    ) -> list[Job]: ...

    @abstractmethod
    def save(self, job: Job) -> Job: ...

    @abstractmethod
    def transition_if(
        self,
        job_id: str,
        expected: JobState,
        new_state: JobState,
    ) -> Optional[Job]: ...

    @abstractmethod
    def complete_if_running(
        self,
        job_id: str,
        new_state: JobState,
        exit_code: int,
        stdout: str,
        stderr: str,
        error: Optional[str],
    ) -> Optional[Job]: ...


class InMemoryJobRepository(JobRepository):
    """
    In-memory repository.

    Every method that reads-then-writes does so without yielding, so under
    asyncio (single thread, cooperative scheduling) they are atomic.
    No locks needed.
    """

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


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, AgentConnection] = {}

    def register(self, agent_id: str, ws: object) -> AgentConnection:
        conn = AgentConnection(agent_id=agent_id, ws=ws)
        self._agents[agent_id] = conn
        return conn

    def unregister(self, agent_id: str) -> None:
        self._agents.pop(agent_id, None)

    def get(self, agent_id: str) -> Optional[AgentConnection]:
        return self._agents.get(agent_id)

    def is_online(self, agent_id: str) -> bool:
        return agent_id in self._agents

    def all(self) -> list[AgentConnection]:
        return list(self._agents.values())