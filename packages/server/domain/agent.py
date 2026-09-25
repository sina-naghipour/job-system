from dataclasses import dataclass, field

from packages.server.domain.job import now


@dataclass
class AgentConnection:
    agent_id: str
    ws: object
    connected_at: str = field(default_factory=now)
    last_heartbeat_at: str = field(default_factory=now)

    def touch(self) -> None:
        self.last_heartbeat_at = now()