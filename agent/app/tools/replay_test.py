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
async def replay_test_handler(job: QueueJob) -> dict | ToolError:
    """Trigger a fresh drift computation on model_service and return the report."""
    settings = get_settings()
    url = f"{settings.model_service_url}/drift/compute"

    log.info(
        "replay_test.start",
        job_id=job.job_id,
        model_name=job.model_name,
        model_version=job.model_version,
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                json={
                    "model_name": job.model_name,
                    "model_version": job.model_version,
                    "investigation_id": job.investigation_id,
                },
            )
            if response.status_code == 200:
                report = response.json()
                log.info(
                    "replay_test.complete",
                    job_id=job.job_id,
                    severity=report.get("severity"),
                )
                return report
            log.warning(
                "replay_test.non_200",
                job_id=job.job_id,
                status=response.status_code,
            )
            return ToolError(
                error=f"model_service /drift/compute returned {response.status_code}",
                retryable=response.status_code >= 500,
            )
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        log.warning("replay_test.network_error", job_id=job.job_id, error=str(exc))
        return ToolError(error=str(exc), retryable=True)
    except Exception as exc:
        log.error("replay_test.unexpected_error", job_id=job.job_id, error=str(exc))
        return ToolError(error=str(exc), retryable=False)
