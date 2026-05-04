
import httpx
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.schemas.tool_io import ToolError

log = structlog.get_logger()


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
    reraise=False,
)
async def fetch_drift_report(drift_report_id: str) -> dict | ToolError:
    settings = get_settings()
    url = f"{settings.model_service_url}/drift/report/{drift_report_id}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            if response.status_code == 200:
                return response.json()
            log.warning(
                "fetch_drift_report.non_200",
                status=response.status_code,
                drift_report_id=drift_report_id,
            )
            return ToolError(
                error=f"model_service returned {response.status_code}",
                retryable=response.status_code >= 500,
            )
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        log.warning("fetch_drift_report.network_error", error=str(exc))
        return ToolError(error=str(exc), retryable=True)
    except Exception as exc:
        log.error("fetch_drift_report.unexpected_error", error=str(exc))
        return ToolError(error=str(exc), retryable=False)
