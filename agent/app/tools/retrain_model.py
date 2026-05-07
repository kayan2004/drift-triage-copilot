import httpx
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.schemas.tool_io import QueueJob, ToolError

log = structlog.get_logger()


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=16),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
    reraise=False,
)
async def retrain_handler(job: QueueJob) -> dict | ToolError:
    """Trigger model retraining via model_service and return the new version details."""
    settings = get_settings()
    url = f"{settings.model_service_url}/registry/retrain"

    log.info(
        "retrain.start",
        job_id=job.job_id,
        model_name=job.model_name,
        investigation_id=job.investigation_id,
    )

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                url,
                json={
                    "model_name": job.model_name,
                    "investigation_id": job.investigation_id,
                    **job.payload,
                },
            )
            # 200 = sync completion with new version; 202 = accepted, training in background
            if response.status_code in (200, 202):
                result = response.json()
                log.info(
                    "retrain.dispatched",
                    job_id=job.job_id,
                    status_code=response.status_code,
                    new_version=result.get("model_version"),
                )
                return result
            log.warning(
                "retrain.non_2xx",
                job_id=job.job_id,
                status=response.status_code,
            )
            return ToolError(
                error=f"model_service /registry/retrain returned {response.status_code}",
                retryable=response.status_code >= 500,
            )
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        log.warning("retrain.network_error", job_id=job.job_id, error=str(exc))
        return ToolError(error=str(exc), retryable=True)
    except httpx.HTTPStatusError as exc:
        log.error("retrain.http_error", job_id=job.job_id, status=exc.response.status_code)
        return ToolError(error=str(exc), retryable=exc.response.status_code >= 500)
