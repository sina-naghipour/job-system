from dataclasses import dataclass, field

from packages.server.domain.job import now


@dataclass
class AgentConnection:
    agent_id: str
    ws: object
    connected_at: str = field(default_factory=now)
    last_heartbeat_at: str = field(default_factory=now)
    in_flight: int = 0

    def touch(self) -> None:
        self.last_heartbeat_at = now()

    def mark_busy(self) -> None:
        self.in_flight += 1

    def mark_free(self) -> None:
        self.in_flight = max(0, self.in_flight - 1)

    @property
    def is_idle(self) -> bool:
        return self.in_flight == 0