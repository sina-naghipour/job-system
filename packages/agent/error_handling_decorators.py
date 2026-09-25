import functools
import logging
from typing import Awaitable, Callable

log = logging.getLogger(__name__)

JobOutcome = tuple[int, str, str]
JobFn = Callable[..., Awaitable[JobOutcome]]


def capture_job_errors(fn: JobFn) -> JobFn:
    @functools.wraps(fn)
    async def wrapper(self, job_id, image, command, *args, **kwargs) -> JobOutcome:
        try:
            return await fn(self, job_id, image, command, *args, **kwargs)
        except Exception as exc:
            log.exception("Job %s failed", job_id)
            return 1, "", str(exc)

    return wrapper