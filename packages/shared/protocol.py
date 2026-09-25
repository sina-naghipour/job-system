from enum import Enum
from typing import Literal, TypedDict


class JobState(str, Enum):
    PENDING = "PENDING"
    DISPATCHED = "DISPATCHED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        return self in TERMINAL_STATES


TERMINAL_STATES = frozenset({
    JobState.SUCCEEDED,
    JobState.FAILED,
    JobState.TIMED_OUT,
    JobState.CANCELLED,
})


# Agent -> Server

class RegisterMessage(TypedDict):
    type: Literal["register"]
    agent_id: str


class AckMessage(TypedDict):
    type: Literal["ack"]
    job_id: str


class StartedMessage(TypedDict):
    type: Literal["started"]
    job_id: str


class LogMessage(TypedDict):
    type: Literal["log"]
    job_id: str
    stream: Literal["stdout", "stderr"]
    sequence: int
    chunk: str


class ResultMessage(TypedDict):
    type: Literal["result"]
    job_id: str
    exit_code: int
    stdout: str
    stderr: str
    error: str | None


class HeartbeatMessage(TypedDict):
    type: Literal["heartbeat"]
    agent_id: str


class ReconcileMessage(TypedDict):
    type: Literal["reconcile"]
    job_id: str
    status: Literal["running"]
    exit_code: int | None


AgentToServer = (
    RegisterMessage
    | AckMessage
    | StartedMessage
    | LogMessage
    | ResultMessage
    | HeartbeatMessage
    | ReconcileMessage
)


# Server -> Agent

class JobMessage(TypedDict):
    type: Literal["job"]
    job_id: str
    correlation_id: str
    image: str
    command: list[str]
    timeout_ms: int


class CancelMessage(TypedDict):
    type: Literal["cancel"]
    job_id: str
    reason: Literal["timeout", "user", "shutdown"]


ServerToAgent = JobMessage | CancelMessage