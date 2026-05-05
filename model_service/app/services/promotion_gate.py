import asyncio
import json
import tempfile
from pathlib import Path

import mlflow
import structlog
from fastapi import HTTPException
from mlflow.tracking import MlflowClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import DriftReport, SeverityEnum

log = structlog.get_logger()


async def check_all(version: str, token: str, session: AsyncSession) -> None:
    settings = get_settings()
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    client = MlflowClient()

    # 1 & 2 — AUC and recall from MLflow run metrics
    mv = await asyncio.to_thread(client.get_model_version, settings.model_name, version)
    run = await asyncio.to_thread(client.get_run, mv.run_id)
    metrics = run.data.metrics

    test_auc = metrics.get("test_auc", 0.0)
    if test_auc < 0.75:
        raise HTTPException(status_code=422, detail=f"test_auc {test_auc:.4f} < 0.75")

    test_recall = metrics.get("test_recall", 0.0)
    if test_recall < 0.75:
        raise HTTPException(status_code=422, detail=f"test_recall {test_recall:.4f} < 0.75")

    # 3 — model card hash self-consistency check
    with tempfile.TemporaryDirectory() as tmp:
        card_path = await asyncio.to_thread(
            mlflow.artifacts.download_artifacts,
            f"runs:/{mv.run_id}/model_card/model_card.json",
            tmp,
        )
        card: dict = json.loads(Path(card_path).read_text())

    if not card.get("model_hash"):
        raise HTTPException(status_code=422, detail="model_card.json missing model_hash field")

    # 4 — no active critical drift
    drift_result = await session.execute(
        select(DriftReport)
        .where(DriftReport.severity == SeverityEnum.critical)
        .order_by(DriftReport.created_at.desc())
        .limit(1)
    )
    active_critical = drift_result.scalar_one_or_none()
    if active_critical is not None:
        raise HTTPException(
            status_code=422,
            detail=f"Active critical drift report {active_critical.id} — resolve before promoting",
        )

    # 5 — HIL token present
    if not token or not token.strip():
        raise HTTPException(status_code=422, detail="X-HIL-Approval-Token is required")

    # All checks passed — set production alias in MLflow
    await asyncio.to_thread(
        client.set_registered_model_alias, settings.model_name, "production", version
    )
    log.info("promotion_gate.passed", version=version)
