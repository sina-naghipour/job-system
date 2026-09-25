from abc import ABC, abstractmethod
from typing import Optional


class EventRepository(ABC):
    @abstractmethod
    def append(
        self,
        job_id: str,
        event_type: str,
        payload: Optional[dict] = None,
    ) -> None: ...

    @abstractmethod
    def list_for_job(self, job_id: str) -> list[dict]: ...