import redis.asyncio as aioredis
import structlog

from app.schemas.tool_io import QueueJob

log = structlog.get_logger()

_SEEN_JOBS_KEY = "triage:seen_jobs"
_JOBS_KEY = "triage:jobs"
_SEEN_JOBS_TTL = 86_400  # 24 h


async def enqueue_job(redis_client: aioredis.Redis, job: QueueJob) -> bool:
    """Push job onto the queue.  Returns False if already seen (idempotent skip)."""
    added = await redis_client.sadd(_SEEN_JOBS_KEY, job.job_id)
    if not added:
        log.info(
            "queue.producer.duplicate_skipped",
            job_id=job.job_id,
            job_type=job.job_type,
            investigation_id=job.investigation_id,
        )
        return False

    # Refresh TTL every time we add (handles first-add and near-expiry top-ups)
    await redis_client.expire(_SEEN_JOBS_KEY, _SEEN_JOBS_TTL)
    await redis_client.lpush(_JOBS_KEY, job.model_dump_json())

    log.info(
        "queue.producer.enqueued",
        job_id=job.job_id,
        job_type=job.job_type,
        investigation_id=job.investigation_id,
        attempt=job.attempt,
    )
    return True
