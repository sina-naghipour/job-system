from abc import ABC, abstractmethod
from typing import Optional


class LogRepository(ABC):
    @abstractmethod
    def append(self, job_id: str, stream: str, sequence: int, chunk: str) -> None: ...

    @abstractmethod
    def list_for_job(
        self,
        job_id: str,
        stream: Optional[str] = None,
    ) -> list[dict]: ...