import asyncio
import logging
import os

import uvicorn

from packages.server.ack_watcher import AckWatcher
from packages.server.api import build_app
from packages.server.gateway import AgentGateway
from packages.server.heartbeat_watcher import HeartbeatWatcher
from packages.server.log_broker import LogBroker
from packages.server.store import AgentRegistry, JobService
from packages.server.timeouts import TimeoutWatcher
from packages.shared.logging_config import configure_logging

from packages.server.repositories import (
    SQLiteEventRepository,
    SQLiteJobRepository,
    SQLiteLogRepository,
)

log = logging.getLogger(__name__)


def build_components(
    host: str,
    ws_port: int,
    db_path: str,
    ack_timeout: float,
    max_attempts: int,
):
    repository = SQLiteJobRepository(db_path)
    log_repository = SQLiteLogRepository(db_path)
    event_repository = SQLiteEventRepository(db_path)
    job_service = JobService(repository)
    registry = AgentRegistry()
    log_broker = LogBroker()

    gateway = AgentGateway(
        job_service=job_service,
        agent_registry=registry,
        log_broker=log_broker,
        log_repository=log_repository,
        event_repository=event_repository,
        host=host,
        port=ws_port,
    )

    timeout_watcher = TimeoutWatcher(
        job_service=job_service,
        gateway=gateway,
        event_repository=event_repository,
    )
    ack_watcher = AckWatcher(
        job_service=job_service,
        gateway=gateway,
        event_repository=event_repository,
        ack_timeout_seconds=ack_timeout,
        max_dispatch_attempts=max_attempts,
    )
    heartbeat_watcher = HeartbeatWatcher(agent_registry=registry)

    return (
        job_service,
        gateway,
        log_broker,
        repository,
        log_repository,
        event_repository,
        timeout_watcher,
        ack_watcher,
        heartbeat_watcher,
    )


async def run_api(app, host: str, port: int) -> None:
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def main() -> None:
    configure_logging("server")

    host = os.getenv("SERVER_HOST", "0.0.0.0")
    ws_port = int(os.getenv("SERVER_PORT", "8080"))
    api_port = int(os.getenv("API_PORT", "8000"))
    db_path = os.getenv("DB_PATH", "data/jobs.db")
    ack_timeout = float(os.getenv("ACK_TIMEOUT_SECONDS", "5"))
    max_attempts = int(os.getenv("MAX_DISPATCH_ATTEMPTS", "3"))

    (
        job_service,
        gateway,
        log_broker,
        repository,
        log_repository,
        event_repository,
        timeout_watcher,
        ack_watcher,
        heartbeat_watcher,
    ) = build_components(host, ws_port, db_path, ack_timeout, max_attempts)

    app = build_app(
        job_service, gateway, log_broker, log_repository, event_repository
    )

    log.info(
        "Server starting",
        extra={"ws_port": ws_port, "api_port": api_port, "db_path": db_path},
    )

    try:
        await asyncio.gather(
            gateway.serve(),
            run_api(app, host, api_port),
            timeout_watcher.run(),
            ack_watcher.run(),
            heartbeat_watcher.run(),
        )
    except asyncio.CancelledError:
        log.info("Server shutting down")
        raise
    finally:
        repository.close()
        log_repository.close()
        event_repository.close()


if __name__ == "__main__":
    asyncio.run(main())