import httpx
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.schemas.tool_io import QueueJob, ToolError

log = structlog.get_logger()


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
    reraise=False,
)
async def rollback_handler(job: QueueJob) -> dict | ToolError:
    """Set the 'staging' alias to a previous model version.

    Does NOT touch the 'production' alias — that requires the promotion gate.
    """
    settings = get_settings()
    target_version = job.payload.get("target_version", "")
    if not target_version:
        return ToolError(error="payload.target_version is required for rollback", retryable=False)

    url = f"{settings.model_service_url}/registry/rollback/{target_version}"

    log.info(
        "rollback.start",
        job_id=job.job_id,
        model_name=job.model_name,
        target_version=target_version,
        investigation_id=job.investigation_id,
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                json={
                    "model_name": job.model_name,
                    "investigation_id": job.investigation_id,
                },
            )
            if response.status_code == 200:
                result = response.json()
                log.info(
                    "rollback.complete",
                    job_id=job.job_id,
                    target_version=target_version,
                )
                return result
            log.warning(
                "rollback.non_200",
                job_id=job.job_id,
                status=response.status_code,
            )
            return ToolError(
                error=f"model_service /registry/rollback returned {response.status_code}",
                retryable=response.status_code >= 500,
            )
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        log.warning("rollback.network_error", job_id=job.job_id, error=str(exc))
        return ToolError(error=str(exc), retryable=True)
    except Exception as exc:
        log.error("rollback.unexpected_error", job_id=job.job_id, error=str(exc))
        return ToolError(error=str(exc), retryable=False)
