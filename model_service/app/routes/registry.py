import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

import mlflow
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient

from app.config import Settings, get_settings
from app.dependencies import get_db_session
from app.schemas.registry import ModelVersionInfo, PromotionRequest
from app.services.promotion_gate import check_all
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()
router = APIRouter(prefix="/registry", tags=["registry"])


def _build_version_info(mv: Any, card: dict) -> ModelVersionInfo:
    aliases = list(mv.aliases) if mv.aliases else []
    return ModelVersionInfo(
        version=mv.version,
        aliases=aliases,
        run_id=mv.run_id,
        model_hash=card.get("model_hash", ""),
        training_date=card.get("training_date", ""),
        test_auc=card.get("test_auc", 0.0),
        test_recall=card.get("test_recall", 0.0),
        threshold=card.get("threshold", 0.5),
    )


async def _fetch_card(run_id: str) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        path = await asyncio.to_thread(
            mlflow.artifacts.download_artifacts,
            artifact_uri=f"runs:/{run_id}/model_card/model_card.json",
            dst_path=tmp,
        )
        return json.loads(Path(path).read_text())


@router.get("/versions", response_model=list[ModelVersionInfo])
async def list_versions(
    settings: Settings = Depends(get_settings),
) -> list[ModelVersionInfo]:
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    client = MlflowClient()
    versions = await asyncio.to_thread(
        client.search_model_versions, f"name='{settings.model_name}'"
    )
    results = []
    for mv in versions:
        try:
            card = await _fetch_card(mv.run_id)
            results.append(_build_version_info(mv, card))
        except Exception as exc:
            log.warning("registry.card_fetch_failed", version=mv.version, run_id=mv.run_id, error=str(exc))
    return results


@router.get("/versions/{version}", response_model=ModelVersionInfo)
async def get_version(
    version: str,
    settings: Settings = Depends(get_settings),
) -> ModelVersionInfo:
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    client = MlflowClient()
    try:
        mv = await asyncio.to_thread(client.get_model_version, settings.model_name, version)
    except MlflowException:
        raise HTTPException(status_code=404, detail=f"Version '{version}' not found")
    card = await _fetch_card(mv.run_id)
    return _build_version_info(mv, card)


@router.post("/retrain", status_code=202)
async def trigger_retrain(
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    log.info("retrain.requested", model_name=settings.model_name)

    async def _run() -> None:
        proc = await asyncio.create_subprocess_exec(
            "docker", "compose", "--profile", "train", "run", "--rm", "model_train",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            log.info("retrain.completed", model_name=settings.model_name)
        else:
            log.error("retrain.failed", returncode=proc.returncode, output=stdout.decode()[-500:])

    asyncio.create_task(_run())
    return {"status": "accepted", "message": "Retrain started in background"}


@router.post("/rollback/{version}", response_model=ModelVersionInfo)
async def rollback_version(
    version: str,
    settings: Settings = Depends(get_settings),
) -> ModelVersionInfo:
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    client = MlflowClient()
    try:
        mv = await asyncio.to_thread(client.get_model_version, settings.model_name, version)
    except MlflowException:
        raise HTTPException(status_code=404, detail=f"Version '{version}' not found")
    await asyncio.to_thread(
        client.set_registered_model_alias,
        name=settings.model_name,
        alias="production",
        version=version,
    )
    card = await _fetch_card(mv.run_id)
    log.info("model.rolled_back", version=version, alias="production")
    return _build_version_info(mv, card)


@router.post("/promote/{version}", response_model=ModelVersionInfo)
async def promote_version(
    version: str,
    body: PromotionRequest,
    x_hil_approval_token: str = Header(...),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_db_session),
) -> ModelVersionInfo:
    await check_all(version=version, token=x_hil_approval_token, session=session)
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    client = MlflowClient()
    mv = await asyncio.to_thread(client.get_model_version, settings.model_name, version)
    card = await _fetch_card(mv.run_id)
    log.info("model.promoted", version=version, alias="production")
    return _build_version_info(mv, card)
