import uuid
from collections import Counter
from datetime import datetime

import numpy as np
import pandas as pd
import structlog
from scipy.stats import chisquare
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DriftReport, SeverityEnum
from app.services.prediction_store import get_recent_predictions

log = structlog.get_logger()

_SEVERITY_ORDER = [SeverityEnum.ok, SeverityEnum.warn, SeverityEnum.critical]


def _max_severity(severities: list[SeverityEnum]) -> SeverityEnum:
    return max(severities, key=lambda s: _SEVERITY_ORDER.index(s))


def compute_psi(reference_pct: list[float], bin_edges: list[float], current: np.ndarray) -> float:
    counts, _ = np.histogram(current, bins=bin_edges)
    total = counts.sum()
    current_pct = counts / max(total, 1)
    eps = 1e-6
    return float(sum(
        (c - r) * np.log((c + eps) / (r + eps))
        for c, r in zip(current_pct, reference_pct, strict=False)
    ))


def classify_psi(psi: float) -> SeverityEnum:
    if psi < 0.1:
        return SeverityEnum.ok
    if psi < 0.25:
        return SeverityEnum.warn
    return SeverityEnum.critical


def compute_chi2_pvalue(reference_proportions: dict, current_values: list) -> float:
    n = len(current_values)
    if n == 0:
        return 1.0
    counts = Counter(current_values)
    all_cats = sorted(set(reference_proportions) | set(counts))
    observed = np.array([counts.get(c, 0) for c in all_cats], dtype=float)
    expected = np.array([reference_proportions.get(c, 1e-6) * n for c in all_cats], dtype=float)
    expected = expected * (observed.sum() / expected.sum())
    _, pvalue = chisquare(observed, f_exp=expected)
    return float(pvalue)


def classify_chi2(pvalue: float) -> SeverityEnum:
    if pvalue > 0.005:
        return SeverityEnum.ok
    if pvalue > 0.001:
        return SeverityEnum.warn
    return SeverityEnum.critical


def classify_output_drift(output_drift: float) -> SeverityEnum:
    if output_drift <= 0.05:
        return SeverityEnum.ok
    if output_drift <= 0.15:
        return SeverityEnum.warn
    return SeverityEnum.critical


async def compute_drift_report(
    session: AsyncSession,
    reference_stats: dict,
    window_size: int,
) -> DriftReport:
    predictions = await get_recent_predictions(session, window_size)

    if not predictions:
        log.warning("drift.no_predictions")
        window_now = datetime.utcnow()
        report = DriftReport(
            id=uuid.uuid4(),
            window_start=window_now,
            window_end=window_now,
            severity=SeverityEnum.ok,
            psi_scores={},
            chi2_scores={},
            output_drift=0.0,
            raw_report={"note": "no predictions in window"},
        )
        session.add(report)
        await session.commit()
        return report

    if len(predictions) < 30:
        log.warning("drift.small_window", n=len(predictions))

    records = [p.input_features for p in predictions]
    df = pd.DataFrame(records)

    window_start = min(p.created_at for p in predictions)
    window_end = max(p.created_at for p in predictions)

    numeric_cols: list[str] = reference_stats["numeric_cols"]
    cat_cols: list[str] = reference_stats["cat_cols"]

    psi_scores: dict[str, float] = {}
    psi_severities: list[SeverityEnum] = []
    for col in numeric_cols:
        ref = reference_stats["numerics"][col]
        current_arr = df[col].dropna().to_numpy(dtype=float)
        psi = compute_psi(ref["reference_pct"], ref["bin_edges"], current_arr)
        psi_scores[col] = round(psi, 6)
        psi_severities.append(classify_psi(psi))

    chi2_scores: dict[str, float] = {}
    chi2_severities: list[SeverityEnum] = []
    for col in cat_cols:
        ref_props = reference_stats["categoricals"][col]
        current_values = df[col].dropna().tolist()
        pvalue = compute_chi2_pvalue(ref_props, current_values)
        chi2_scores[col] = round(pvalue, 6)
        chi2_severities.append(classify_chi2(pvalue))

    positive_rate = sum(p.label for p in predictions) / len(predictions)
    ref_positive_rate = reference_stats["output"]["positive_rate"]
    output_drift = abs(positive_rate - ref_positive_rate)
    output_severity = classify_output_drift(output_drift)

    all_severities = psi_severities + chi2_severities + [output_severity]
    severity = _max_severity(all_severities)

    raw_report = {
        "n_predictions": len(predictions),
        "positive_rate": round(positive_rate, 6),
        "ref_positive_rate": round(ref_positive_rate, 6),
        "psi_severities": {col: psi_severities[i].value for i, col in enumerate(numeric_cols)},
        "chi2_severities": {col: chi2_severities[i].value for i, col in enumerate(cat_cols)},
        "output_severity": output_severity.value,
    }

    report = DriftReport(
        id=uuid.uuid4(),
        window_start=window_start,
        window_end=window_end,
        severity=severity,
        psi_scores=psi_scores,
        chi2_scores=chi2_scores,
        output_drift=round(output_drift, 6),
        raw_report=raw_report,
    )
    session.add(report)
    await session.commit()

    log.info(
        "drift.computed",
        severity=severity.value,
        n_predictions=len(predictions),
        output_drift=round(output_drift, 4),
    )
    return report
