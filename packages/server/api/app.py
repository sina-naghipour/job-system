import asyncio
import json
import logging
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from packages.server.gateway import AgentGateway
from packages.server.repositories import (
    SQLiteEventRepository,
    SQLiteLogRepository,
)
from packages.server.services import JobService, LogBroker, LogChunk

log = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 0.5


class SubmitJobRequest(BaseModel):
    agentId: str = Field(min_length=1)
    image: str = Field(min_length=1)
    command: list[str] = Field(min_length=1)
    timeoutMs: int = Field(gt=0, default=60_000)
    idempotencyKey: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class SubmitJobResponse(BaseModel):
    jobId: str


class JobListResponse(BaseModel):
    jobs: list[dict]


class CancelJobResponse(BaseModel):
    jobId: str
    state: str


def _format_log_event(chunk: LogChunk) -> str:
    payload = json.dumps({
        "stream": chunk.stream,
        "sequence": chunk.sequence,
        "chunk": chunk.chunk,
    })
    return f"event: log\ndata: {payload}\n\n"


def _format_end_event() -> str:
    return "event: end\ndata: {}\n\n"


def build_router(
    job_service: JobService,
    gateway: AgentGateway,
    log_broker: LogBroker,
    log_repository: SQLiteLogRepository,
    event_repository: SQLiteEventRepository,
) -> APIRouter:
    router = APIRouter()

    @router.post("/jobs", response_model=SubmitJobResponse, status_code=202)
    async def submit_job(req: SubmitJobRequest) -> SubmitJobResponse:
        job = job_service.submit(
            agent_id=req.agentId,
            image=req.image,
            command=req.command,
            timeout_ms=req.timeoutMs,
            idempotency_key=req.idempotencyKey,
            metadata=req.metadata,
        )
        event_repository.append(job.job_id, "submitted", {
            "agent_id": job.agent_id,
            "image": job.image,
        })
        log.info("Job submitted", extra={
            "job_id": job.job_id,
            "correlation_id": job.correlation_id,
            "agent_id": job.agent_id,
        })
        try:
            await gateway.dispatch_pending(req.agentId)
        except Exception:
            log.exception("Dispatch after submit failed", extra={"job_id": job.job_id})
        return SubmitJobResponse(jobId=job.job_id)

    @router.get("/jobs", response_model=JobListResponse)
    async def list_jobs(
        agentId: Optional[str] = None,
        state: Optional[str] = None,
    ) -> JobListResponse:
        jobs = job_service.list(agent_id=agentId, state=state)
        return JobListResponse(jobs=[j.to_dict() for j in jobs])

    @router.get("/jobs/{job_id}")
    async def get_job(job_id: str) -> dict:
        job = job_service.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return job.to_dict()

    @router.get("/jobs/{job_id}/result")
    async def get_result(job_id: str) -> dict:
        job = job_service.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return job.to_result()

    @router.post(
        "/jobs/{job_id}/cancel",
        response_model=CancelJobResponse,
        status_code=202,
    )
    async def cancel_job(job_id: str) -> CancelJobResponse:
        job = job_service.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if job.state.is_terminal:
            raise HTTPException(
                status_code=409,
                detail=f"Job is already {job.state.value}",
            )

        await gateway.send_cancel(job.agent_id, job_id, reason="user")
        updated = job_service.mark_cancelled(job_id)
        event_repository.append(job_id, "cancelled", {"by": "user"})
        state = updated.state.value if updated else job.state.value
        return CancelJobResponse(jobId=job_id, state=state)

    @router.get("/jobs/{job_id}/logs")
    async def get_logs(
        job_id: str,
        stream: Optional[str] = None,
    ) -> Response:
        job = job_service.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")

        entries = log_repository.list_for_job(job_id, stream=stream)
        body = "".join(e["chunk"] for e in entries)
        return Response(content=body, media_type="text/plain")

    @router.get("/jobs/{job_id}/logs/live")
    async def stream_logs(job_id: str) -> StreamingResponse:
        job = job_service.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")

        return StreamingResponse(
            _log_stream(job_service, log_broker, job_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @router.get("/jobs/{job_id}/events")
    async def get_events(job_id: str) -> dict:
        job = job_service.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return {"events": event_repository.list_for_job(job_id)}

    return router


async def _log_stream(
    job_service: JobService,
    log_broker: LogBroker,
    job_id: str,
) -> AsyncGenerator[str, None]:
    queue, history = log_broker.subscribe(job_id)
    try:
        for chunk in history:
            yield _format_log_event(chunk)

        job = job_service.get(job_id)
        if job is not None and job.state.is_terminal:
            yield _format_end_event()
            return

        while True:
            try:
                chunk = await asyncio.wait_for(queue.get(), timeout=POLL_INTERVAL_SECONDS)
                yield _format_log_event(chunk)
                continue
            except asyncio.TimeoutError:
                pass

            job = job_service.get(job_id)
            if job is None or job.state.is_terminal:
                break

        while not queue.empty():
            yield _format_log_event(queue.get_nowait())

        yield _format_end_event()
    finally:
        log_broker.unsubscribe(job_id, queue)


def build_app(
    job_service: JobService,
    gateway: AgentGateway,
    log_broker: LogBroker,
    log_repository: SQLiteLogRepository,
    event_repository: SQLiteEventRepository,
) -> FastAPI:
    app = FastAPI(title="Job System API", version="0.1.0")
    app.include_router(
        build_router(
            job_service, gateway, log_broker, log_repository, event_repository
        )
    )
    return app