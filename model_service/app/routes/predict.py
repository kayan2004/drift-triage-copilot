import asyncio
import uuid

import pandas as pd
import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Prediction
from app.dependencies import get_db_session, get_model
from app.schemas.prediction import PredictionRequest, PredictionResponse
from app.services.model_loader import ModelBundle

log = structlog.get_logger()
router = APIRouter(prefix="/predict", tags=["predictions"])


@router.post("/", response_model=PredictionResponse)
async def predict(
    body: PredictionRequest,
    model_bundle: ModelBundle = Depends(get_model),
    session: AsyncSession = Depends(get_db_session),
) -> PredictionResponse:
    features = body.model_dump()
    df = pd.DataFrame([features])

    proba: float = await asyncio.to_thread(
        lambda: float(model_bundle.pipeline.predict_proba(df)[0, 1])
    )

    label_int = 1 if proba >= model_bundle.threshold else 0
    label_str = "subscribed" if label_int == 1 else "not_subscribed"
    pred_id = str(uuid.uuid4())

    row = Prediction(
        id=uuid.UUID(pred_id),
        input_features=features,
        probability=proba,
        label=label_int,
        model_version=model_bundle.model_version,
        threshold=model_bundle.threshold,
    )
    session.add(row)
    await session.commit()

    log.info(
        "prediction.made",
        prediction_id=pred_id,
        label=label_str,
        probability=round(proba, 4),
        model_version=model_bundle.model_version,
    )

    return PredictionResponse(
        prediction_id=pred_id,
        label=label_str,
        probability=round(proba, 6),
        model_version=model_bundle.model_version,
        threshold=model_bundle.threshold,
    )
