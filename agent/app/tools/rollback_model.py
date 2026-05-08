import httpx
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.schemas.tool_io import QueueJob, ToolError

log = structlog.get_logger()


async def _find_rollback_target(base_url: str, current_version: str) -> str | None:
    """Query /registry/versions and return the best version to roll back to.

    Prefers the version with the 'staging' alias. Falls back to the highest
    version number that is not the current production version.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{base_url}/registry/versions")
            if response.status_code != 200:
                return None
            versions: list[dict] = response.json()
    except (httpx.TimeoutException, httpx.NetworkError):
        return None

    # Prefer the staging alias
    for v in versions:
        if "staging" in v.get("aliases", []) and v["version"] != current_version:
            return v["version"]

    # Fall back to highest version that isn't current production
    others = [v for v in versions if v["version"] != current_version]
    if not others:
        return None
    return max(others, key=lambda v: int(v["version"]))["version"]


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
    reraise=False,
)
async def rollback_handler(job: QueueJob) -> dict | ToolError:
    """Set the 'production' alias to a previous model version and hot-reload the model."""
    settings = get_settings()
    base_url = settings.model_service_url

    target_version = job.payload.get("target_version", "")

    if not target_version:
        current_version = job.model_version
        target_version = await _find_rollback_target(base_url, current_version) or ""

    if not target_version:
        return ToolError(
            error="No previous version found to roll back to — only one version exists in the registry",
            retryable=False,
        )

    url = f"{base_url}/registry/rollback/{target_version}"

    log.info(
        "rollback.start",
        job_id=job.job_id,
        model_name=job.model_name,
        current_version=job.model_version,
        target_version=target_version,
        investigation_id=job.investigation_id,
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url)
            if response.status_code == 200:
                result = response.json()
                log.info(
                    "rollback.complete",
                    job_id=job.job_id,
                    rolled_back_to=target_version,
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
    except httpx.HTTPStatusError as exc:
        log.error("rollback.http_error", job_id=job.job_id, status=exc.response.status_code)
        return ToolError(error=str(exc), retryable=exc.response.status_code >= 500)
