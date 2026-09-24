import asyncio
import logging
import os

import uvicorn

from packages.server.api import build_app
from packages.server.gateway import AgentGateway
from packages.server.sqlite_repository import SQLiteJobRepository
from packages.server.store import AgentRegistry, JobService
from packages.shared.logging_config import configure_logging

log = logging.getLogger(__name__)


def build_components(
    host: str, ws_port: int, db_path: str
) -> tuple[JobService, AgentGateway, SQLiteJobRepository]:
    repository = SQLiteJobRepository(db_path)
    job_service = JobService(repository)
    registry = AgentRegistry()

    gateway = AgentGateway(
        job_service=job_service,
        agent_registry=registry,
        host=host,
        port=ws_port,
    )
    return job_service, gateway, repository


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

    job_service, gateway, repository = build_components(host, ws_port, db_path)
    app = build_app(job_service, gateway)

    log.info(
        "Server starting: ws=ws://%s:%s api=http://%s:%s db=%s",
        host, ws_port, host, api_port, db_path,
    )

    try:
        await asyncio.gather(
            gateway.serve(),
            run_api(app, host, api_port),
        )
    except asyncio.CancelledError:
        log.info("Server shutting down")
        raise
    finally:
        repository.close()


if __name__ == "__main__":
    asyncio.run(main())