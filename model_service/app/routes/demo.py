"""Demo-only routes — reset and batch prediction generation."""
import asyncio
import random
import uuid
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Prediction
from app.dependencies import get_db_session, get_model
from app.services.model_loader import ModelBundle

import pandas as pd

log = structlog.get_logger()
router = APIRouter(prefix="/demo", tags=["demo"])


# ── Reference-anchored samplers ───────────────────────────────────────────────
# Economic features are bimodal — sampled by picking a bin from reference
# proportions then drawing uniformly within that bin's edges.

def _bin_sample(edges: list[float], weights: list[float]) -> float:
    """Pick a bin according to weights, then sample uniformly within it."""
    # filter zero-weight bins
    nonzero = [(w, edges[i], edges[i+1]) for i, w in enumerate(weights) if w > 0]
    ws = [x[0] for x in nonzero]
    chosen = random.choices(nonzero, weights=ws)[0]
    return round(random.uniform(chosen[1], chosen[2]), 3)


def _econ() -> dict:
    # Exact bin edges and proportions from training/reference_stats.json
    return {
        "emp_var_rate": _bin_sample(
            [-3.4, -2.92, -2.44, -1.96, -1.48, -1.0, -0.52, -0.04, 0.44, 0.92, 1.4],
            [0.030, 0.040, 0.0, 0.244, 0.015, 0.0, 0.089, 0.0, 0.0, 0.582],
        ),
        "euribor3m": _bin_sample(
            [0.63, 1.08, 1.52, 1.96, 2.4, 2.84, 3.28, 3.72, 4.16, 4.6, 5.04],
            [0.103, 0.220, 0.006, 0.0, 0.0, 0.0, 0.0, 0.071, 0.015, 0.584],
        ),
        "nr_employed": _bin_sample(
            [4963.6, 4990.1, 5016.5, 5043.0, 5069.4, 5095.9, 5122.3, 5148.8, 5175.2, 5201.7, 5228.1],
            [0.015, 0.035, 0.030, 0.0, 0.040, 0.209, 0.0, 0.0, 0.276, 0.395],
        ),
        "cons_price_idx": _bin_sample(
            [92.20, 92.46, 92.71, 92.97, 93.23, 93.48, 93.74, 94.00, 94.25, 94.51, 94.77],
            [0.036, 0.017, 0.166, 0.147, 0.132, 0.0, 0.361, 0.027, 0.106, 0.008],
        ),
        "cons_conf_idx": _bin_sample(
            [-50.8, -48.4, -46.0, -43.6, -41.2, -38.9, -36.5, -34.1, -31.7, -29.3, -26.9],
            [0.014, 0.202, 0.0, 0.356, 0.038, 0.013, 0.324, 0.009, 0.033, 0.011],
        ),
    }


def _sample_normal() -> dict:
    return {
        "age":             random.choices(range(25, 60), weights=[1]*35)[0],
        "job":             random.choices(["admin.", "technician", "blue-collar", "services", "management"], weights=[25, 16, 22, 10, 7])[0],
        "marital":         random.choices(["married", "single", "divorced"], weights=[60, 28, 12])[0],
        "education":       random.choices(["university.degree", "high.school", "basic.9y", "professional.course"], weights=[30, 23, 18, 14])[0],
        "default":         "no",
        "housing":         random.choices(["yes", "no"], weights=[52, 48])[0],
        "loan":            random.choices(["yes", "no"], weights=[17, 83])[0],
        "contact":         random.choices(["cellular", "telephone"], weights=[64, 36])[0],
        "month":           random.choices(["may", "jul", "aug", "jun", "nov"], weights=[33, 17, 15, 13, 10])[0],
        "day_of_week":     random.choices(["mon", "tue", "wed", "thu", "fri"], weights=[20, 20, 20, 20, 20])[0],
        "campaign":        random.choices([1, 2, 3], weights=[70, 20, 10])[0],
        "pdays_contacted": random.choices([0, 1], weights=[96, 4])[0],
        "previous":        random.choices([0, 1, 2], weights=[86, 11, 3])[0],
        "poutcome":        random.choices(["nonexistent", "failure", "success"], weights=[86, 10, 4])[0],
        **_econ(),
    }


def _sample_mild() -> dict:
    # Age skews 45-65, more campaign contacts, more telephone.
    # Economic features stay on-distribution so only demographic PSI rises.
    return {
        "age":             random.choices(range(45, 66), weights=[1]*21)[0],
        "job":             random.choices(["admin.", "technician", "blue-collar", "retired", "services"], weights=[20, 15, 20, 15, 10])[0],
        "marital":         random.choices(["married", "single", "divorced"], weights=[65, 20, 15])[0],
        "education":       random.choices(["high.school", "university.degree", "basic.9y", "professional.course"], weights=[35, 25, 22, 14])[0],
        "default":         "no",
        "housing":         random.choices(["yes", "no"], weights=[55, 45])[0],
        "loan":            random.choices(["yes", "no"], weights=[20, 80])[0],
        "contact":         random.choices(["cellular", "telephone"], weights=[35, 65])[0],
        "month":           random.choices(["aug", "sep", "oct", "nov"], weights=[30, 25, 25, 20])[0],
        "day_of_week":     random.choices(["mon", "tue", "wed", "thu", "fri"], weights=[20, 20, 20, 20, 20])[0],
        "campaign":        random.choices([3, 4, 5, 6], weights=[40, 30, 20, 10])[0],
        "pdays_contacted": 0,
        "previous":        random.choices([0, 1], weights=[90, 10])[0],
        "poutcome":        random.choices(["nonexistent", "failure"], weights=[90, 10])[0],
        **_econ(),
    }


def _sample_drifted() -> dict:
    # Extreme shift on all features including economic indicators.
    return {
        "age":             random.choices(range(65, 91), weights=[1]*26)[0],
        "job":             random.choices(["retired", "blue-collar", "unknown"], weights=[70, 20, 10])[0],
        "marital":         random.choices(["divorced", "married", "single"], weights=[50, 35, 15])[0],
        "education":       random.choices(["basic.4y", "basic.6y", "basic.9y", "unknown"], weights=[40, 25, 25, 10])[0],
        "default":         random.choices(["unknown", "no"], weights=[60, 40])[0],
        "housing":         random.choices(["unknown", "no", "yes"], weights=[50, 30, 20])[0],
        "loan":            random.choices(["unknown", "no"], weights=[50, 50])[0],
        "contact":         "telephone",
        "month":           random.choices(["dec", "nov", "oct"], weights=[70, 20, 10])[0],
        "day_of_week":     random.choices(["fri", "mon"], weights=[70, 30])[0],
        "campaign":        random.choices(range(10, 21), weights=[1]*11)[0],
        "pdays_contacted": 0,
        "previous":        0,
        "poutcome":        "nonexistent",
        # Economic indicators also shifted — high-rate environment only
        "emp_var_rate":    random.choices([1.1, 1.2, 1.4], weights=[20, 20, 60])[0],
        "cons_price_idx":  round(random.uniform(93.8, 94.8), 3),
        "cons_conf_idx":   round(random.uniform(-50.0, -42.0), 1),
        "euribor3m":       round(random.uniform(4.5, 5.0), 3),
        "nr_employed":     random.choices([5191.0, 5215.0, 5228.1], weights=[30, 30, 40])[0],
    }


_SAMPLERS = {
    "normal":  _sample_normal,
    "mild":    _sample_mild,
    "drifted": _sample_drifted,
}


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/reset", status_code=200)
async def reset_demo(
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    await session.execute(text("DELETE FROM predictions"))
    await session.execute(text("DELETE FROM drift_reports"))
    await session.commit()
    log.info("demo.reset", tables=["predictions", "drift_reports"])
    return {"status": "ok", "cleared": ["predictions", "drift_reports"]}


@router.post("/batch/{profile}", status_code=200)
async def send_batch(
    profile: Literal["normal", "mild", "drifted"],
    n: int = 50,
    session: AsyncSession = Depends(get_db_session),
    model_bundle: ModelBundle = Depends(get_model),
) -> dict[str, Any]:
    """Send N varied predictions drawn from the given profile distribution."""
    sampler = _SAMPLERS[profile]
    rows = []
    for _ in range(n):
        features = sampler()
        df = pd.DataFrame([features])
        proba: float = await asyncio.to_thread(
            lambda f=df: float(model_bundle.pipeline.predict_proba(f)[0, 1])
        )
        label_int = 1 if proba >= model_bundle.threshold else 0
        rows.append(Prediction(
            id=uuid.uuid4(),
            input_features=features,
            probability=proba,
            label=label_int,
            model_version=model_bundle.model_version,
            threshold=model_bundle.threshold,
        ))
    session.add_all(rows)
    await session.commit()
    log.info("demo.batch_sent", profile=profile, n=n)
    return {"status": "ok", "profile": profile, "sent": n}
