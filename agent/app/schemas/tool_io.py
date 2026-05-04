from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ToolError(BaseModel):
    error: str
    retryable: bool


class TriageAssessment(BaseModel):
    drifting_features: list[str]
    drift_hypothesis: Literal["data_quality", "distribution_shift", "seasonal", "unknown"]
    recommended_actions: list[Literal["replay_test", "retrain", "rollback", "monitor_only"]]
    urgency: Literal["low", "medium", "high", "critical"]


class ActionDecision(BaseModel):
    chosen_action: Literal["replay_test", "retrain", "rollback", "monitor_only", "await_human"]
    requires_human_approval: bool
    justification: str
    queue_job_id: str | None = None


class CommsReport(BaseModel):
    summary: str
    actions_taken: list[str]
    next_steps: str
    investigation_status: Literal["open", "resolved", "escalated"]


class QueueJob(BaseModel):
    job_id: str = Field(..., description="uuid4 — idempotency key")
    job_type: Literal["replay_test", "retrain", "rollback"]
    model_name: str
    model_version: str
    investigation_id: str
    created_at: datetime
    attempt: int = 0
    max_attempts: int = 3
    payload: dict = Field(default_factory=dict)

    @field_validator("attempt")
    @classmethod
    def attempt_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("attempt must be >= 0")
        return v
