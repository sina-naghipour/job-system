import asyncio
import logging

from packages.server.services import AgentRegistry

log = logging.getLogger(__name__)

DEFAULT_SCAN_INTERVAL = 1.0
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 10.0
DEFAULT_MISSED_BEATS_BEFORE_OFFLINE = 3


class HeartbeatWatcher:
    def __init__(
        self,
        agent_registry: AgentRegistry,
        heartbeat_interval_seconds: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
        missed_beats_before_offline: int = DEFAULT_MISSED_BEATS_BEFORE_OFFLINE,
        scan_interval: float = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        self._agents = agent_registry
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._missed_beats_before_offline = missed_beats_before_offline
        self._scan_interval = scan_interval

    async def run(self) -> None:
        max_idle = self._heartbeat_interval_seconds * self._missed_beats_before_offline
        log.info(
            "Heartbeat watcher started (max idle=%.1fs, interval=%.1fs)",
            max_idle,
            self._scan_interval,
        )
        while True:
            try:
                await self._scan()
            except Exception:
                log.exception("Heartbeat scan failed")
            await asyncio.sleep(self._scan_interval)

    async def _scan(self) -> None:
        max_idle = self._heartbeat_interval_seconds * self._missed_beats_before_offline
        for conn in self._agents.stale_agents(max_idle):
            log.warning(
                "Agent %s missed %d heartbeats; marking offline",
                conn.agent_id,
                self._missed_beats_before_offline,
            )
            self._agents.unregister(conn.agent_id)