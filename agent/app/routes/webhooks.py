import hashlib
import hmac
import uuid

import structlog
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request

from app.config import get_settings
from app.schemas.webhook import DriftWebhookPayload

log = structlog.get_logger()
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _verify_signature(body: bytes, signature: str, secret: str) -> None:
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(f"sha256={expected}", signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


def _verify_version(version: str) -> None:
    if version != "1.0":
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported webhook version: {version}. Expected 1.0",
        )


async def _run_investigation(
    investigation_id: str,
    payload: DriftWebhookPayload,
    request: Request,
) -> None:
    store = request.app.state.store
    graph = request.app.state.graph
    config = {
        "configurable": {
            "thread_id": investigation_id,
            "llm_client": request.app.state.llm,
            "redis_client": request.app.state.redis,
        }
    }

    try:
        initial_state = {
            "drift_event": payload,
            "triage_result": None,
            "action_decision": None,
            "hil_approved": False,
            "hil_token": None,
            "comms_result": None,
            "investigation_id": investigation_id,
            "messages": [],
        }
        async for chunk in graph.astream(initial_state, config=config):
            node_name = list(chunk.keys())[0] if chunk else "unknown"
            log.info(
                "investigation.node_complete",
                investigation_id=investigation_id,
                node=node_name,
            )

        # Check final state
        final = await graph.aget_state(config)
        state_vals = final.values if final else {}
        action = state_vals.get("action_decision")

        triage = state_vals.get("triage_result")
        triage_summary = (
            f"{triage.urgency} urgency — {triage.drift_hypothesis} — features: {', '.join(triage.drifting_features)}"
            if triage else None
        )

        if action and action.requires_human_approval and not state_vals.get("hil_approved"):
            # Graph interrupted — waiting for HIL
            token = str(uuid.uuid4())
            await store.update_status(
                investigation_id,
                status="awaiting_approval",
                proposed_action=action.chosen_action,
                hil_token=token,
                triage_summary=triage_summary,
            )
            log.info("investigation.awaiting_hil", investigation_id=investigation_id)
        else:
            comms = state_vals.get("comms_result")
            final_status = comms.investigation_status if comms else "resolved"
            await store.update_status(
                investigation_id,
                status=final_status,
                triage_summary=triage_summary,
            )
            log.info(
                "investigation.complete",
                investigation_id=investigation_id,
                status=final_status,
            )
    except Exception as exc:
        # Background task: update status before re-raising so dashboard always reflects reality.
        log.error("investigation.error", investigation_id=investigation_id, error=str(exc))
        await store.update_status(investigation_id, status="escalated")
        raise

#^
@router.post("/drift", status_code=202)
async def receive_drift_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_webhook_signature: str = Header(..., alias="X-Webhook-Signature"),
    x_webhook_version: str = Header("1.0", alias="X-Webhook-Version"),
) -> dict:
    body = await request.body()
    settings = get_settings()
    _verify_version(x_webhook_version)
    _verify_signature(body, x_webhook_signature, settings.webhook_secret)

    payload = DriftWebhookPayload.model_validate_json(body)
    # Thread ID = event_id per CLAUDE.md — one LangGraph thread per investigation
    investigation_id = payload.event_id

    store = request.app.state.store
    await store.create(payload, investigation_id)

    log.info(
        "webhook.received",
        event_id=payload.event_id,
        investigation_id=investigation_id,
        severity=payload.severity,
    )

    background_tasks.add_task(_run_investigation, investigation_id, payload, request)
    return {"investigation_id": investigation_id, "status": "accepted"}

