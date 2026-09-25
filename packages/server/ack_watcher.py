import asyncio
import logging
from datetime import datetime, timezone

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
        ack_timeout_seconds: float = DEFAULT_ACK_TIMEOUT_SECONDS,
        max_dispatch_attempts: int = DEFAULT_MAX_DISPATCH_ATTEMPTS,
        scan_interval: float = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        self._job_service = job_service
        self._gateway = gateway
        self._ack_timeout_seconds = ack_timeout_seconds
        self._max_dispatch_attempts = max_dispatch_attempts
        self._scan_interval = scan_interval

    async def run(self) -> None:
        log.info(
            "Ack watcher started (timeout=%.1fs, max_attempts=%d, interval=%.1fs)",
            self._ack_timeout_seconds,
            self._max_dispatch_attempts,
            self._scan_interval,
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
                "Job %s exceeded max dispatch attempts (%d); marking FAILED",
                job.job_id,
                self._max_dispatch_attempts,
            )
            self._job_service.fail_stale_dispatch(
                job.job_id,
                error=f"No ack after {self._max_dispatch_attempts} dispatch attempts",
            )
            return

        log.warning(
            "No ack for job %s after %.1fs; requeueing (attempt %d)",
            job.job_id,
            self._ack_timeout_seconds,
            job.dispatch_attempts,
        )
        self._job_service.requeue(job.job_id)
        await self._gateway.dispatch_pending(job.agent_id)