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


def configure_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s [server] %(levelname)s %(message)s",
    )


def build_components() -> tuple[JobService, AgentGateway]:
    repository = InMemoryJobRepository()
    job_service = JobService(repository)
    registry = AgentRegistry()

    gateway = AgentGateway(
        job_service=job_service,
        agent_registry=registry,
        host=os.getenv("SERVER_HOST", "0.0.0.0"),
        port=int(os.getenv("SERVER_PORT", "8080")),
    )
    return job_service, gateway


async def run_api(app, host: str, port: int) -> None:
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def main() -> None:
    configure_logging()
    job_service, gateway = build_components()

    api_host = os.getenv("SERVER_HOST", "0.0.0.0")
    api_port = int(os.getenv("API_PORT", "8000"))

    app = build_app(job_service, gateway)

    await asyncio.gather(
        gateway.serve(),
        run_api(app, api_host, api_port),
    )


if __name__ == "__main__":
    asyncio.run(main())