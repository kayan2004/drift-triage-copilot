import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import DriftReport
from app.dependencies import get_db_session, get_model
from app.routes.webhook import emit_drift_webhook
from app.schemas.drift_report import DriftReportResponse, DriftWebhookPayload
from app.services.drift_calculator import compute_drift_report
from app.services.model_loader import ModelBundle

log = structlog.get_logger()
router = APIRouter(prefix="/drift", tags=["drift"])


def _to_response(report: DriftReport) -> DriftReportResponse:
    return DriftReportResponse(
        id=str(report.id),
        created_at=report.created_at,
        window_start=report.window_start,
        window_end=report.window_end,
        severity=report.severity.value,
        psi_scores=report.psi_scores or {},
        chi2_scores=report.chi2_scores or {},
        output_drift=report.output_drift or 0.0,
        raw_report=report.raw_report,
    )


async def _get_latest_report(session: AsyncSession) -> DriftReport | None:
    result = await session.execute(
        select(DriftReport).order_by(DriftReport.created_at.desc()).limit(1)
    )
    return result.scalar_one_or_none()


@router.get("/report/{report_id}", response_model=DriftReportResponse)
async def get_drift_report_by_id(
    report_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> DriftReportResponse:
    result = await session.execute(select(DriftReport).where(DriftReport.id == report_id))
    report = result.scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail=f"Drift report '{report_id}' not found")
    return _to_response(report)


@router.get("/report", response_model=DriftReportResponse)
async def get_latest_drift_report(
    session: AsyncSession = Depends(get_db_session),
) -> DriftReportResponse:
    report = await _get_latest_report(session)
    if report is None:
        raise HTTPException(
            status_code=404,
            detail="No drift report found — run POST /drift/compute first",
        )
    return _to_response(report)


@router.post("/compute", response_model=DriftReportResponse)
async def trigger_drift_compute(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    model_bundle: ModelBundle = Depends(get_model),
    settings: Settings = Depends(get_settings),
) -> DriftReportResponse:
    previous = await _get_latest_report(session)
    previous_severity = previous.severity.value if previous else "ok"

    report = await compute_drift_report(
        session=session,
        reference_stats=model_bundle.reference_stats,
        window_size=settings.drift_window_size,
    )

    if report.severity.value != previous_severity:
        payload = DriftWebhookPayload(
            severity=report.severity.value,
            previous_severity=previous_severity,
            model_name=settings.model_name,
            model_version=model_bundle.model_version,
            drift_report_id=str(report.id),
            psi_summary=report.psi_scores or {},
            chi2_summary=report.chi2_scores or {},
            output_drift=report.output_drift or 0.0,
        )
        log.info("webhook.emitting", previous=previous_severity, new=report.severity.value)
        await emit_drift_webhook(payload, settings)

    return _to_response(report)
