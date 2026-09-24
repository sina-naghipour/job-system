import logging
from typing import Optional

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, Field

from packages.server.gateway import AgentGateway
from packages.server.store import JobService

log = logging.getLogger(__name__)


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


def build_router(job_service: JobService, gateway: AgentGateway) -> APIRouter:
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
        try:
            await gateway.dispatch_pending(req.agentId)
        except Exception:
            log.exception("Dispatch after submit failed for %s", job.job_id)
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

    return router


def build_app(job_service: JobService, gateway: AgentGateway) -> FastAPI:
    app = FastAPI(title="Job System API", version="0.1.0")
    app.include_router(build_router(job_service, gateway))
    return app