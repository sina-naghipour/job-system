import pytest

from packages.server.gateway import AgentGateway
from packages.server.store import (
    AgentRegistry,
    InMemoryJobRepository,
    JobService,
)


@pytest.fixture
def repository() -> InMemoryJobRepository:
    return InMemoryJobRepository()


@pytest.fixture
def job_service(repository: InMemoryJobRepository) -> JobService:
    return JobService(repository)


@pytest.fixture
def agent_registry() -> AgentRegistry:
    return AgentRegistry()


@pytest.fixture
def gateway(job_service: JobService, agent_registry: AgentRegistry) -> AgentGateway:
    return AgentGateway(
        job_service=job_service,
        agent_registry=agent_registry,
        host="127.0.0.1",
        port=0,
    )