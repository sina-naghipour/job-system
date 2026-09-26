import logging

from packages.server.services import AgentRegistry
from packages.server.watchers.base import BaseWatcher

log = logging.getLogger(__name__)

DEFAULT_SCAN_INTERVAL = 1.0
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 10.0
DEFAULT_MISSED_BEATS_BEFORE_OFFLINE = 3


class HeartbeatWatcher(BaseWatcher):
    def __init__(
        self,
        agent_registry: AgentRegistry,
        heartbeat_interval_seconds: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
        missed_beats_before_offline: int = DEFAULT_MISSED_BEATS_BEFORE_OFFLINE,
        scan_interval: float = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        super().__init__(scan_interval=scan_interval)
        self._agents = agent_registry
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._missed_beats_before_offline = missed_beats_before_offline

    async def _scan(self) -> None:
        max_idle = self._heartbeat_interval_seconds * self._missed_beats_before_offline
        for conn in self._agents.stale_agents(max_idle):
            log.warning(
                "Agent marked offline after missed heartbeats",
                extra={
                    "agent_id": conn.agent_id,
                    "missed_beats": self._missed_beats_before_offline,
                },
            )
            self._agents.unregister(conn.agent_id)