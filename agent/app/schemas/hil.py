from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class HILApprovalRequest(BaseModel):
    approved: bool
    approver_note: str = ""


class HILApprovalToken(BaseModel):
    token: str = Field(..., description="Opaque token passed to model_service on promotion")
    investigation_id: str
    issued_at: datetime
    action: str


class InvestigationSummary(BaseModel):
    investigation_id: str
    event_id: str
    severity: Literal["ok", "warn", "critical"]
    model_name: str
    model_version: str
    status: Literal["open", "awaiting_approval", "resolved", "escalated", "rejected"]
    started_at: datetime
    updated_at: datetime
    triage_summary: str | None = None
    proposed_action: str | None = None


class InvestigationDetail(InvestigationSummary):
    messages: list[dict] = Field(default_factory=list)
    hil_token: str | None = None
