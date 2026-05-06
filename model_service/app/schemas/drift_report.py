import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class DriftReportResponse(BaseModel):
    id: str
    created_at: datetime
    window_start: datetime
    window_end: datetime
    severity: str
    psi_scores: dict
    chi2_scores: dict
    output_drift: float
    raw_report: dict | None


class DriftWebhookPayload(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: Literal["drift_alert"] = "drift_alert"
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    severity: str
    previous_severity: str
    model_name: str
    model_version: str
    drift_report_id: str
    psi_summary: dict
    chi2_summary: dict
    output_drift: float
    webhook_version: str = "1.0"
