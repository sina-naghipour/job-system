from datetime import datetime, timezone
from typing import Optional

from packages.server.domain import AgentConnection


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, AgentConnection] = {}

    def register(self, agent_id: str, ws: object) -> AgentConnection:
        conn = AgentConnection(agent_id=agent_id, ws=ws)
        self._agents[agent_id] = conn
        return conn

    def unregister(self, agent_id: str) -> None:
        self._agents.pop(agent_id, None)

    def get(self, agent_id: str) -> Optional[AgentConnection]:
        return self._agents.get(agent_id)

    def is_online(self, agent_id: str) -> bool:
        return agent_id in self._agents

    def all(self) -> list[AgentConnection]:
        return list(self._agents.values())

    def touch(self, agent_id: str) -> None:
        conn = self._agents.get(agent_id)
        if conn is not None:
            conn.touch()

    def stale_agents(self, max_idle_seconds: float) -> list[AgentConnection]:
        cutoff = datetime.now(timezone.utc).timestamp() - max_idle_seconds
        stale: list[AgentConnection] = []
        for conn in self._agents.values():
            last = datetime.fromisoformat(conn.last_heartbeat_at).timestamp()
            if last < cutoff:
                stale.append(conn)
        return stale