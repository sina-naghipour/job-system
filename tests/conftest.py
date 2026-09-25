import pytest

from packages.server.gateway import AgentGateway
from packages.server.log_broker import LogBroker
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
def log_broker() -> LogBroker:
    return LogBroker()


@pytest.fixture
def gateway(
    job_service: JobService,
    agent_registry: AgentRegistry,
    log_broker: LogBroker,
) -> AgentGateway:
    return AgentGateway(
        job_service=job_service,
        agent_registry=agent_registry,
        log_broker=log_broker,
        host="127.0.0.1",
        port=0,
    )