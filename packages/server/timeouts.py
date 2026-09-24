import asyncio
import logging
from datetime import datetime, timezone

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
        scan_interval: float = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        self._job_service = job_service
        self._gateway = gateway
        self._scan_interval = scan_interval

    async def run(self) -> None:
        log.info("Timeout watcher started (interval=%.1fs)", self._scan_interval)
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
        log.warning("Job %s exceeded timeout (%dms)", job.job_id, job.timeout_ms)
        sent = await self._gateway.send_cancel(job.agent_id, job.job_id, reason="timeout")
        if not sent:
            log.warning("Cancel not delivered for %s: agent offline", job.job_id)
        self._job_service.mark_timed_out(job.job_id)