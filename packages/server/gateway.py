import asyncio
import json
import logging
from typing import Optional

import websockets
from websockets.asyncio.server import ServerConnection

from packages.server.error_handling_decorators import (
    with_connection_guard,
    with_dispatch_guard,
    with_send_guard,
)
from packages.server.log_broker import LogBroker
from packages.server.store import AgentRegistry, JobService
from packages.shared.protocol import (
    AgentToServer,
    CancelMessage,
    JobMessage,
    JobState,
)

log = logging.getLogger(__name__)


class AgentGateway:
    def __init__(
        self,
        job_service: JobService,
        agent_registry: AgentRegistry,
        log_broker: LogBroker,
        host: str = "0.0.0.0",
        port: int = 8080,
    ) -> None:
        self._job_service = job_service
        self._agents = agent_registry
        self._log_broker = log_broker
        self._host = host
        self._port = port
        self._dispatch_locks: dict[str, asyncio.Lock] = {}

    async def serve(self) -> None:
        async with websockets.serve(self._handle_connection, self._host, self._port):
            log.info("Agent gateway listening on ws://%s:%s", self._host, self._port)
            await asyncio.Future()

    def _lock_for(self, agent_id: str) -> asyncio.Lock:
        lock = self._dispatch_locks.get(agent_id)
        if lock is None:
            lock = asyncio.Lock()
            self._dispatch_locks[agent_id] = lock
        return lock

    @with_connection_guard
    async def _handle_connection(self, ws: ServerConnection) -> None:
        agent_id: Optional[str] = None
        try:
            async for raw in ws:
                message = self._parse_message(raw)
                if message is None:
                    continue
                agent_id = await self._safe_dispatch(ws, message, agent_id)
        except websockets.ConnectionClosed:
            log.info("Agent disconnected: %s", agent_id)
        finally:
            if agent_id:
                self._agents.unregister(agent_id)
                self._dispatch_locks.pop(agent_id, None)

    def _parse_message(self, raw: str) -> Optional[AgentToServer]:
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            log.warning("Ignoring malformed message: %r", raw[:200])
            return None

    @with_dispatch_guard
    async def _safe_dispatch(
        self,
        ws: ServerConnection,
        message: AgentToServer,
        agent_id: Optional[str],
    ) -> Optional[str]:
        return await self._dispatch(ws, message, agent_id)

    async def _dispatch(
        self,
        ws: ServerConnection,
        message: AgentToServer,
        agent_id: Optional[str],
    ) -> Optional[str]:
        message_type = message.get("type")
        if message_type is None:
            log.warning("Message missing 'type' field")
            return agent_id

        handlers = {
            "register": self._on_register,
            "ack": self._on_ack,
            "started": self._on_started,
            "log": self._on_log,
            "result": self._on_result,
            "heartbeat": self._on_heartbeat,
        }
        handler = handlers.get(message_type)
        if handler is None:
            log.warning("Unknown message type: %s", message_type)
            return agent_id
        return await handler(ws, message, agent_id)

    async def _on_register(
        self,
        ws: ServerConnection,
        message: dict,
        agent_id: Optional[str],
    ) -> str:
        new_agent_id = message["agent_id"]
        self._agents.register(new_agent_id, ws)
        log.info("Agent registered: %s", new_agent_id)
        await self.dispatch_pending(new_agent_id)
        return new_agent_id

    async def _on_ack(
        self, ws: ServerConnection, message: dict, agent_id: Optional[str]
    ) -> Optional[str]:
        log.debug("Ack for %s", message["job_id"])
        return agent_id

    async def _on_started(
        self, ws: ServerConnection, message: dict, agent_id: Optional[str]
    ) -> Optional[str]:
        job = self._job_service.mark_running(message["job_id"])
        if job:
            log.info("Job %s is RUNNING", job.job_id)
        return agent_id

    async def _on_log(
        self, ws: ServerConnection, message: dict, agent_id: Optional[str]
    ) -> Optional[str]:
        self._log_broker.publish(
            job_id=message["job_id"],
            stream=message["stream"],
            chunk=message["chunk"],
        )
        return agent_id

    async def _on_result(
        self, ws: ServerConnection, message: dict, agent_id: Optional[str]
    ) -> Optional[str]:
        job_id = message["job_id"]
        exit_code = message["exit_code"]
        stdout = message.get("stdout", "")
        stderr = message.get("stderr", "")
        error = message.get("error")

        if error:
            job = self._job_service.mark_failed(job_id, exit_code, stdout, stderr, error)
        elif exit_code == 0:
            job = self._job_service.mark_succeeded(job_id, exit_code, stdout, stderr)
        else:
            job = self._job_service.mark_failed(job_id, exit_code, stdout, stderr)

        if job:
            log.info(
                "Job %s finished: state=%s exit_code=%s",
                job.job_id, job.state.value, job.exit_code,
            )
        return agent_id

    async def _on_heartbeat(
        self, ws: ServerConnection, message: dict, agent_id: Optional[str]
    ) -> Optional[str]:
        return agent_id

    async def send_cancel(self, agent_id: str, job_id: str, reason: str) -> bool:
        conn = self._agents.get(agent_id)
        if conn is None:
            return False
        message: CancelMessage = {
            "type": "cancel",
            "job_id": job_id,
            "reason": reason,
        }
        return await self._send(conn.ws, message)

    async def dispatch_pending(self, agent_id: str) -> None:
        async with self._lock_for(agent_id):
            conn = self._agents.get(agent_id)
            if conn is None:
                return

            pending = self._job_service.list(agent_id=agent_id, state=JobState.PENDING)
            pending = sorted(pending, key=lambda j: j.created_at)

            for job in pending:
                message: JobMessage = {
                    "type": "job",
                    "job_id": job.job_id,
                    "image": job.image,
                    "command": job.command,
                    "timeout_ms": job.timeout_ms,
                }
                if not await self._send(conn.ws, message):
                    return
                self._job_service.mark_dispatched(job.job_id)
                log.info("Dispatched %s to %s", job.job_id, agent_id)

    @with_send_guard
    async def _send(self, ws: ServerConnection, message: dict) -> None:
        await ws.send(json.dumps(message))