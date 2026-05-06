import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, HTTPException, Request

from app.queue.producer import enqueue_job
from app.schemas.hil import (
    HILApprovalRequest,
    InvestigationDetail,
    InvestigationSummary,
)
from app.schemas.tool_io import QueueJob

log = structlog.get_logger()
router = APIRouter(prefix="/investigations", tags=["investigations"])


@router.get("/", response_model=list[InvestigationSummary])
async def list_investigations(
    request: Request,
    status: str | None = None,
) -> list[InvestigationSummary]:
    return await request.app.state.store.list_all(status=status)


@router.get("/{investigation_id}", response_model=InvestigationDetail)
async def get_investigation(investigation_id: str, request: Request) -> InvestigationDetail:
    detail = await request.app.state.store.get(investigation_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return detail


@router.post("/{investigation_id}/approve", status_code=200)
async def approve_investigation(
    investigation_id: str,
    body: HILApprovalRequest,
    request: Request,
) -> dict:
    store = request.app.state.store
    detail = await store.get(investigation_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    if detail.status != "awaiting_approval":
        raise HTTPException(
            status_code=422,
            detail=f"Investigation is not awaiting approval (status={detail.status})",
        )

    graph = request.app.state.graph
    config = {
        "configurable": {
            "thread_id": investigation_id,
            "llm_client": request.app.state.llm,
            "redis_client": request.app.state.redis,
        }
    }

    if not body.approved:
        await store.update_status(investigation_id, status="rejected")
        log.info("investigation.hil_rejected", investigation_id=investigation_id)
        return {"investigation_id": investigation_id, "status": "rejected"}

    log.info(
        "investigation.hil_approved",
        investigation_id=investigation_id,
        approver_note=body.approver_note,
    )

    # Dispatch the queue job here — action_agent couldn't enqueue it on first pass
    # because hil_approved was False. Supervisor routes await_hil → comms directly
    # on resume, so action_agent never re-runs. We own dispatch at this boundary.
    current = await graph.aget_state(config)
    state_vals = current.values if current else {}
    action = state_vals.get("action_decision")
    drift_event = state_vals.get("drift_event")

    queue_job_id: str | None = None
    if action and drift_event and action.chosen_action not in ("monitor_only", "await_human"):
        queue_job_id = str(uuid.uuid4())
        queue_job = QueueJob(
            job_id=queue_job_id,
            job_type=action.chosen_action,  # type: ignore[arg-type]
            model_name=drift_event.model_name,
            model_version=drift_event.model_version,
            investigation_id=investigation_id,
            created_at=datetime.now(tz=UTC),
        )
        await enqueue_job(request.app.state.redis, queue_job)
        log.info(
            "investigation.job_dispatched",
            investigation_id=investigation_id,
            job_id=queue_job_id,
            action=action.chosen_action,
        )

    # Inject hil_approved + queue_job_id before resuming
    state_update: dict = {"hil_approved": True, "hil_token": detail.hil_token}
    if queue_job_id and action:
        state_update["action_decision"] = action.model_copy(
            update={"queue_job_id": queue_job_id}
        )
    await graph.aupdate_state(config, state_update)

    # Resume graph — await_hil → supervisor → comms_agent → END
    async for chunk in graph.astream(None, config=config):
        node_name = list(chunk.keys())[0] if chunk else "unknown"
        log.info(
            "investigation.resumed_node",
            investigation_id=investigation_id,
            node=node_name,
        )

    final = await graph.aget_state(config)
    final_vals = final.values if final else {}
    comms = final_vals.get("comms_result")
    final_status = comms.investigation_status if comms else "resolved"
    await store.update_status(investigation_id, status=final_status)

    return {
        "investigation_id": investigation_id,
        "status": final_status,
        "hil_token": detail.hil_token,
        "queue_job_id": queue_job_id,
    }
