from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class DriftWebhookPayload(BaseModel):
    event_id: str = Field(..., description="uuid4 — used as LangGraph thread ID")
    event_type: Literal["drift_alert"]
    timestamp: datetime
    severity: Literal["ok", "warn", "critical"]
    previous_severity: Literal["ok", "warn", "critical"]
    model_name: str
    model_version: str
    drift_report_id: str
    psi_summary: dict[str, float] = Field(default_factory=dict)
    chi2_summary: dict[str, float] = Field(default_factory=dict)
    output_drift: float
    webhook_version: str = "1.0"

    @field_validator("output_drift")
    @classmethod
    def output_drift_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("output_drift must be non-negative")
        return v
