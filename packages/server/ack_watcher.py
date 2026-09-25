import asyncio
import logging
from datetime import datetime, timezone

from packages.server.repositories import SQLiteEventRepository
from packages.server.gateway import AgentGateway
from packages.server.store import JobService
from packages.shared.protocol import JobState

log = logging.getLogger(__name__)

DEFAULT_SCAN_INTERVAL = 1.0
DEFAULT_ACK_TIMEOUT_SECONDS = 5.0
DEFAULT_MAX_DISPATCH_ATTEMPTS = 3


class AckWatcher:
    def __init__(
        self,
        job_service: JobService,
        gateway: AgentGateway,
        event_repository: SQLiteEventRepository,
        ack_timeout_seconds: float = DEFAULT_ACK_TIMEOUT_SECONDS,
        max_dispatch_attempts: int = DEFAULT_MAX_DISPATCH_ATTEMPTS,
        scan_interval: float = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        self._job_service = job_service
        self._gateway = gateway
        self._event_repository = event_repository
        self._ack_timeout_seconds = ack_timeout_seconds
        self._max_dispatch_attempts = max_dispatch_attempts
        self._scan_interval = scan_interval

    async def run(self) -> None:
        log.info(
            "Ack watcher started",
            extra={
                "ack_timeout_seconds": self._ack_timeout_seconds,
                "max_dispatch_attempts": self._max_dispatch_attempts,
                "scan_interval": self._scan_interval,
            },
        )
        while True:
            try:
                await self._scan()
            except Exception:
                log.exception("Ack scan failed")
            await asyncio.sleep(self._scan_interval)

    async def _scan(self) -> None:
        now = datetime.now(timezone.utc)
        for job in self._job_service.list(state=JobState.DISPATCHED):
            updated = datetime.fromisoformat(job.updated_at)
            age_seconds = (now - updated).total_seconds()
            if age_seconds > self._ack_timeout_seconds:
                await self._on_ack_timeout(job)

    async def _on_ack_timeout(self, job) -> None:
        if job.dispatch_attempts >= self._max_dispatch_attempts:
            log.warning(
                "Job exceeded max dispatch attempts",
                extra={
                    "job_id": job.job_id,
                    "correlation_id": job.correlation_id,
                    "agent_id": job.agent_id,
                    "attempts": job.dispatch_attempts,
                },
            )
            self._job_service.fail_stale_dispatch(
                job.job_id,
                error=f"No ack after {self._max_dispatch_attempts} dispatch attempts",
            )
            self._event_repository.append(
                job.job_id,
                "failed",
                {"reason": "no_ack", "attempts": job.dispatch_attempts},
            )
            return

        log.warning(
            "No ack received; requeueing",
            extra={
                "job_id": job.job_id,
                "correlation_id": job.correlation_id,
                "agent_id": job.agent_id,
                "attempt": job.dispatch_attempts,
            },
        )
        self._job_service.requeue(job.job_id)
        self._event_repository.append(
            job.job_id, "requeued", {"attempt": job.dispatch_attempts}
        )
        await self._gateway.dispatch_pending(job.agent_id)