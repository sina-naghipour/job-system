import asyncio
import logging
from datetime import datetime, timezone

from packages.server.event_repository import SQLiteEventRepository
from packages.server.gateway import AgentGateway
from packages.server.store import JobService
from packages.shared.protocol import JobState

log = logging.getLogger(__name__)

DEFAULT_SCAN_INTERVAL = 1.0


class TimeoutWatcher:
    def __init__(
        self,
        job_service: JobService,
        gateway: AgentGateway,
        event_repository: SQLiteEventRepository,
        scan_interval: float = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        self._job_service = job_service
        self._gateway = gateway
        self._event_repository = event_repository
        self._scan_interval = scan_interval

    async def run(self) -> None:
        log.info("Timeout watcher started", extra={"interval": self._scan_interval})
        while True:
            try:
                await self._scan()
            except Exception:
                log.exception("Timeout scan failed")
            await asyncio.sleep(self._scan_interval)

    async def _scan(self) -> None:
        now = datetime.now(timezone.utc)
        for job in self._job_service.list(state=JobState.RUNNING):
            if job.started_at is None:
                continue
            started = datetime.fromisoformat(job.started_at)
            elapsed_ms = (now - started).total_seconds() * 1000
            if elapsed_ms > job.timeout_ms:
                await self._fire(job)

    async def _fire(self, job) -> None:
        log.warning(
            "Job exceeded timeout",
            extra={
                "job_id": job.job_id,
                "correlation_id": job.correlation_id,
                "agent_id": job.agent_id,
                "timeout_ms": job.timeout_ms,
            },
        )
        sent = await self._gateway.send_cancel(job.agent_id, job.job_id, reason="timeout")
        if not sent:
            log.warning(
                "Cancel not delivered for job",
                extra={"job_id": job.job_id, "reason": "agent offline"},
            )
        self._job_service.mark_timed_out(job.job_id)
        self._event_repository.append(
            job.job_id, "timed_out", {"timeout_ms": job.timeout_ms}
        )