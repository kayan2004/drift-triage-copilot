import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ModelVersion
from app.dependencies import get_db_session, get_model
from app.schemas.registry import ModelVersionInfo, PromotionRequest
from app.services.model_loader import ModelBundle
from app.services.promotion_gate import check_all

log = structlog.get_logger()
router = APIRouter(prefix="/registry", tags=["registry"])


@router.get("/versions", response_model=list[ModelVersionInfo])
async def list_versions(
    session: AsyncSession = Depends(get_db_session),
) -> list[ModelVersion]:
    result = await session.execute(
        select(ModelVersion).order_by(ModelVersion.registered_at.desc())
    )
    return list(result.scalars().all())


@router.get("/versions/{version}", response_model=ModelVersionInfo)
async def get_version(
    version: str,
    session: AsyncSession = Depends(get_db_session),
) -> ModelVersion:
    result = await session.execute(
        select(ModelVersion).where(ModelVersion.version == version)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Version '{version}' not found")
    return row


@router.post("/promote/{version}", response_model=ModelVersionInfo)
async def promote_version(
    version: str,
    body: PromotionRequest,
    x_hil_approval_token: str = Header(...),
    session: AsyncSession = Depends(get_db_session),
    model_bundle: ModelBundle = Depends(get_model),
) -> ModelVersion:
    await check_all(version=version, token=x_hil_approval_token, session=session)

    result = await session.execute(
        select(ModelVersion).where(ModelVersion.version == version)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Version '{version}' not found in DB")

    row.alias = "production"
    row.is_active = True
    await session.commit()
    await session.refresh(row)

    log.info("model.promoted", version=version, alias="production")
    return row
