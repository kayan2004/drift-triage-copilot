import json

import structlog
from fastapi import APIRouter, HTTPException, Request

log = structlog.get_logger()
router = APIRouter(prefix="/queue", tags=["queue"])

_JOBS_KEY = "triage:jobs"
_DLQ_KEY = "triage:dlq"


@router.get("/depth")
async def queue_depth(request: Request) -> dict:
    redis = request.app.state.redis
    jobs = await redis.llen(_JOBS_KEY)
    dlq = await redis.llen(_DLQ_KEY)
    return {"jobs": jobs, "dlq": dlq}


@router.get("/dlq")
async def list_dlq(request: Request, limit: int = 50) -> list[dict]:
    redis = request.app.state.redis
    raw_items = await redis.lrange(_DLQ_KEY, 0, limit - 1)
    result = []
    for raw in raw_items:
        try:
            result.append(json.loads(raw))
        except json.JSONDecodeError:
            result.append({"raw": raw})
    return result


@router.post("/dlq/{job_id}/requeue", status_code=202)
async def requeue_dlq_job(job_id: str, request: Request) -> dict:
    redis = request.app.state.redis
    raw_items = await redis.lrange(_DLQ_KEY, 0, -1)

    target_raw = None
    for raw in raw_items:
        try:
            entry = json.loads(raw)
            if entry.get("job_id") == job_id:
                target_raw = raw
                break
        except json.JSONDecodeError:
            continue

    if target_raw is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found in DLQ")

    # Remove from DLQ and re-enqueue — reset attempt counter
    await redis.lrem(_DLQ_KEY, 1, target_raw)
    entry = json.loads(target_raw)
    entry["attempt"] = 0
    entry.pop("dlq_error", None)
    await redis.lpush(_JOBS_KEY, json.dumps(entry))

    log.info("dlq.requeued", job_id=job_id)
    return {"job_id": job_id, "status": "requeued"}


@router.delete("/dlq/{job_id}", status_code=200)
async def dismiss_dlq_job(job_id: str, request: Request) -> dict:
    redis = request.app.state.redis
    raw_items = await redis.lrange(_DLQ_KEY, 0, -1)

    for raw in raw_items:
        try:
            entry = json.loads(raw)
            if entry.get("job_id") == job_id:
                await redis.lrem(_DLQ_KEY, 1, raw)
                log.info("dlq.dismissed", job_id=job_id)
                return {"job_id": job_id, "status": "dismissed"}
        except json.JSONDecodeError:
            continue

    raise HTTPException(status_code=404, detail=f"Job {job_id} not found in DLQ")
