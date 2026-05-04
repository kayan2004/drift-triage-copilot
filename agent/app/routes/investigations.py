import structlog
from fastapi import APIRouter, HTTPException, Request

from app.schemas.hil import (
    HILApprovalRequest,
    InvestigationDetail,
    InvestigationSummary,
)

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
    config = {"configurable": {"thread_id": investigation_id}}

    if not body.approved:
        await store.update_status(investigation_id, status="rejected")
        log.info("investigation.hil_rejected", investigation_id=investigation_id)
        return {"investigation_id": investigation_id, "status": "rejected"}

    log.info(
        "investigation.hil_approved",
        investigation_id=investigation_id,
        approver_note=body.approver_note,
    )

    # Resume the graph from the interrupt point with hil_approved=True.
    # Re-inject non-serializable singletons (lost across checkpoint boundary).
    await graph.aupdate_state(
        config,
        {
            "hil_approved": True,
            "hil_token": detail.hil_token,
            "llm_client": request.app.state.llm,
            "redis_client": request.app.state.redis,
        },
    )

    # Continue running the graph
    async for chunk in graph.astream(None, config=config):
        node_name = list(chunk.keys())[0] if chunk else "unknown"
        log.info(
            "investigation.resumed_node",
            investigation_id=investigation_id,
            node=node_name,
        )

    final = await graph.aget_state(config)
    state_vals = final.values if final else {}
    comms = state_vals.get("comms_result")
    final_status = comms.investigation_status if comms else "resolved"
    await store.update_status(investigation_id, status=final_status)

    return {
        "investigation_id": investigation_id,
        "status": final_status,
        "hil_token": detail.hil_token,
    }
