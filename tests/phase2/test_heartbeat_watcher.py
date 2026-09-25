from datetime import datetime, timedelta, timezone

import pytest

from packages.server.heartbeat_watcher import HeartbeatWatcher
from packages.server.services import LogBroker
from packages.server.services import JobService, AgentRegistry


class FakeWebSocket:
    pass


def _agent(registry: AgentRegistry, agent_id: str, *, age_seconds: float):
    conn = registry.register(agent_id, FakeWebSocket())
    old = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    conn.last_heartbeat_at = old.isoformat()
    return conn


async def test_fresh_heartbeat_is_kept_online() -> None:
    registry = AgentRegistry()
    _agent(registry, "agent-1", age_seconds=5)
    watcher = HeartbeatWatcher(
        registry,
        heartbeat_interval_seconds=10.0,
        missed_beats_before_offline=3,
    )

    await watcher._scan()

    assert registry.is_online("agent-1")


async def test_stale_agent_is_unregistered() -> None:
    registry = AgentRegistry()
    _agent(registry, "agent-1", age_seconds=40)
    watcher = HeartbeatWatcher(
        registry,
        heartbeat_interval_seconds=10.0,
        missed_beats_before_offline=3,
    )

    await watcher._scan()

    assert not registry.is_online("agent-1")


async def test_multiple_agents_each_evaluated() -> None:
    registry = AgentRegistry()
    _agent(registry, "fresh", age_seconds=5)
    _agent(registry, "stale", age_seconds=40)
    watcher = HeartbeatWatcher(
        registry,
        heartbeat_interval_seconds=10.0,
        missed_beats_before_offline=3,
    )

    await watcher._scan()

    assert registry.is_online("fresh")
    assert not registry.is_online("stale")


async def test_touch_keeps_agent_alive() -> None:
    registry = AgentRegistry()
    _agent(registry, "agent-1", age_seconds=40)
    # Agent sends a heartbeat just before the scan.
    registry.touch("agent-1")
    watcher = HeartbeatWatcher(
        registry,
        heartbeat_interval_seconds=10.0,
        missed_beats_before_offline=3,
    )

    await watcher._scan()

    assert registry.is_online("agent-1")