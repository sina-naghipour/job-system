import asyncio
import logging
import os

import uvicorn

from packages.server.api import build_app
from packages.server.gateway import AgentGateway
from packages.server.store import (
    AgentRegistry,
    InMemoryJobRepository,
    JobService,
)
from packages.shared.logging_config import configure_logging

log = logging.getLogger(__name__)


def build_components(host: str, ws_port: int) -> tuple[JobService, AgentGateway]:
    repository = InMemoryJobRepository()
    job_service = JobService(repository)
    registry = AgentRegistry()

    gateway = AgentGateway(
        job_service=job_service,
        agent_registry=registry,
        host=host,
        port=ws_port,
    )
    return job_service, gateway


async def run_api(app, host: str, port: int) -> None:
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def main() -> None:
    configure_logging("server")

    host = os.getenv("SERVER_HOST", "0.0.0.0")
    ws_port = int(os.getenv("SERVER_PORT", "8080"))
    api_port = int(os.getenv("API_PORT", "8000"))

    job_service, gateway = build_components(host, ws_port)
    app = build_app(job_service, gateway)

    log.info("Starting server: ws=ws://%s:%s api=http://%s:%s", host, ws_port, host, api_port)

    try:
        await asyncio.gather(
            gateway.serve(),
            run_api(app, host, api_port),
        )
    except asyncio.CancelledError:
        log.info("Server shutting down")
        raise


if __name__ == "__main__":
    asyncio.run(main())