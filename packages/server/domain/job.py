import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from packages.shared.protocol import JobState


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_job_id() -> str:
    return f"job_{uuid.uuid4().hex[:12]}"


@dataclass
class Job:
    # identity
    job_id: str
    # request
    agent_id: str
    image: str
    command: list[str]
    timeout_ms: int
    # request (optional)
    metadata: dict = field(default_factory=dict)
    idempotency_key: Optional[str] = None
    priority: int = 0
    # identity (generated)
    correlation_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    # state machine
    state: JobState = JobState.PENDING
    created_at: str = field(default_factory=now)
    updated_at: str = field(default_factory=now)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    # dispatch
    dispatch_attempts: int = 0
    # outcome
    exit_code: Optional[int] = None
    error: Optional[str] = None
    stdout: str = ""
    stderr: str = ""

    def to_dict(self) -> dict:
        return {
            "jobId": self.job_id,
            "agentId": self.agent_id,
            "image": self.image,
            "command": self.command,
            "timeoutMs": self.timeout_ms,
            "idempotencyKey": self.idempotency_key,
            "priority": self.priority,
            "metadata": self.metadata,
            "state": self.state.value,
            "exitCode": self.exit_code,
            "error": self.error,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "correlationId": self.correlation_id,
            "dispatchAttempts": self.dispatch_attempts,
        }

    def to_result(self) -> dict:
        return {
            "jobId": self.job_id,
            "state": self.state.value,
            "exitCode": self.exit_code,
            "error": self.error,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }