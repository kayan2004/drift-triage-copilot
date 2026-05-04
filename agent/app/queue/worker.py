"""Standalone queue worker process.

Start with:
    uv run python -m app.queue.worker

Consumes jobs from triage:jobs via BRPOP, routes to the appropriate handler,
retries transient failures with exponential backoff, and moves exhausted jobs
to triage:dlq.
"""
import asyncio
import json
import math
import sys

import redis.asyncio as aioredis
import structlog
from pydantic import ValidationError

from app.config import get_settings
from app.schemas.tool_io import QueueJob, ToolError
from app.tools.replay_test import replay_test_handler
from app.tools.retrain_model import retrain_handler
from app.tools.rollback_model import rollback_handler

log = structlog.get_logger()

_JOBS_KEY = "triage:jobs"
_DLQ_KEY = "triage:dlq"
_BRPOP_TIMEOUT = 5  # seconds — allows clean shutdown on SIGTERM

_HANDLERS = {
    "replay_test": replay_test_handler,
    "retrain": retrain_handler,
    "rollback": rollback_handler,
}


def _backoff_seconds(attempt: int) -> float:
    """Exponential backoff: 2^attempt capped at 60 s."""
    return min(60.0, math.pow(2, attempt))


async def _process_job(redis_client: aioredis.Redis, job: QueueJob) -> None:
    handler = _HANDLERS.get(job.job_type)
    if handler is None:
        log.error("worker.unknown_job_type", job_type=job.job_type, job_id=job.job_id)
        await _send_to_dlq(redis_client, job, error=f"no handler for job_type={job.job_type}")
        return

    log.info(
        "worker.processing",
        job_id=job.job_id,
        job_type=job.job_type,
        attempt=job.attempt,
        investigation_id=job.investigation_id,
    )

    result: dict | ToolError = await handler(job)

    if isinstance(result, ToolError):
        if result.retryable and job.attempt < job.max_attempts - 1:
            delay = _backoff_seconds(job.attempt)
            next_job = job.model_copy(update={"attempt": job.attempt + 1})
            log.warning(
                "worker.retrying",
                job_id=job.job_id,
                attempt=next_job.attempt,
                delay_s=delay,
                error=result.error,
            )
            await asyncio.sleep(delay)
            await redis_client.lpush(_JOBS_KEY, next_job.model_dump_json())
        else:
            reason = "max_attempts_exceeded" if not result.retryable else "non_retryable_error"
            log.error(
                "worker.job_failed",
                job_id=job.job_id,
                reason=reason,
                error=result.error,
            )
            await _send_to_dlq(redis_client, job, error=result.error)
        return

    log.info(
        "worker.job_complete",
        job_id=job.job_id,
        job_type=job.job_type,
        investigation_id=job.investigation_id,
        result_keys=list(result.keys()),
    )


async def _send_to_dlq(redis_client: aioredis.Redis, job: QueueJob, error: str) -> None:
    dlq_entry = job.model_dump()
    dlq_entry["dlq_error"] = error
    await redis_client.lpush(_DLQ_KEY, json.dumps(dlq_entry, default=str))
    log.warning("worker.dlq", job_id=job.job_id, job_type=job.job_type, error=error)


async def run_worker() -> None:
    settings = get_settings()
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    log.info("worker.started", queue=_JOBS_KEY)

    try:
        while True:
            item = await redis_client.brpop(_JOBS_KEY, timeout=_BRPOP_TIMEOUT)
            if item is None:
                continue

            _, raw = item
            try:
                job = QueueJob.model_validate_json(raw)
            except ValidationError as exc:
                log.error("worker.parse_error", raw=raw[:200], error=str(exc))
                continue

            await _process_job(redis_client, job)
    except asyncio.CancelledError:
        log.info("worker.shutdown")
    finally:
        await redis_client.aclose()


if __name__ == "__main__":
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        sys.exit(0)
