from abc import ABC, abstractmethod
from typing import Optional

from packages.server.domain import Job
from packages.shared.protocol import JobState


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