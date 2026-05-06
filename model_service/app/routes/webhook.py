import hashlib
import hmac

import httpx
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import Settings
from app.schemas.drift_report import DriftWebhookPayload

log = structlog.get_logger()


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=10),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
    reraise=True,
)
async def _post_webhook(url: str, body: bytes, headers: dict) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, content=body, headers=headers)
        response.raise_for_status()


async def emit_drift_webhook(payload: DriftWebhookPayload, settings: Settings) -> None:
    url = f"{settings.agent_url}/webhooks/drift"
    body = payload.model_dump_json().encode()
    sig = hmac.new(settings.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Signature": f"sha256={sig}",
        "X-Webhook-Version": "1.0",
    }
    try:
        await _post_webhook(url, body, headers)
        log.info("webhook.emitted", severity=payload.severity, report_id=payload.drift_report_id)
    except Exception as exc:
        log.error("webhook.failed", error=str(exc), url=url)
