"""Pydantic schema tests — every model: valid input accepted, invalid raises ValidationError."""
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.hil import HILApprovalRequest, HILApprovalToken, InvestigationSummary
from app.schemas.tool_io import (
    ActionDecision,
    CommsReport,
    QueueJob,
    ToolError,
    TriageAssessment,
)
from app.schemas.webhook import DriftWebhookPayload

# ---------------------------------------------------------------------------
# DriftWebhookPayload
# ---------------------------------------------------------------------------

def _valid_webhook() -> dict:
    return {
        "event_id": "evt-abc-123",
        "event_type": "drift_alert",
        "timestamp": "2025-05-01T10:00:00Z",
        "severity": "critical",
        "previous_severity": "warn",
        "model_name": "bank_churn_classifier",
        "model_version": "1",
        "drift_report_id": "rpt-001",
        "psi_summary": {"euribor3m": 0.35},
        "chi2_summary": {"job": 0.005},
        "output_drift": 0.14,
    }


def test_webhook_valid() -> None:
    p = DriftWebhookPayload(**_valid_webhook())
    assert p.severity == "critical"
    assert p.webhook_version == "1.0"


def test_webhook_rejects_invalid_severity() -> None:
    with pytest.raises(ValidationError):
        DriftWebhookPayload(**{**_valid_webhook(), "severity": "catastrophic"})


def test_webhook_rejects_invalid_event_type() -> None:
    with pytest.raises(ValidationError):
        DriftWebhookPayload(**{**_valid_webhook(), "event_type": "unknown_type"})


def test_webhook_rejects_negative_output_drift() -> None:
    with pytest.raises(ValidationError):
        DriftWebhookPayload(**{**_valid_webhook(), "output_drift": -0.1})


def test_webhook_rejects_missing_required_field() -> None:
    data = _valid_webhook()
    del data["model_name"]
    with pytest.raises(ValidationError):
        DriftWebhookPayload(**data)


# ---------------------------------------------------------------------------
# QueueJob
# ---------------------------------------------------------------------------

def _valid_job() -> dict:
    return {
        "job_id": "550e8400-e29b-41d4-a716-446655440000",
        "job_type": "retrain",
        "model_name": "bank_churn_classifier",
        "model_version": "1",
        "investigation_id": "inv-001",
        "created_at": datetime.now(tz=UTC),
    }


def test_queue_job_valid() -> None:
    job = QueueJob(**_valid_job())
    assert job.attempt == 0
    assert job.max_attempts == 3


def test_queue_job_id_is_36_chars() -> None:
    job = QueueJob(**_valid_job())
    assert len(job.job_id) == 36


def test_queue_job_rejects_invalid_job_type() -> None:
    with pytest.raises(ValidationError):
        QueueJob(**{**_valid_job(), "job_type": "delete_everything"})


def test_queue_job_rejects_negative_attempt() -> None:
    with pytest.raises(ValidationError):
        QueueJob(**{**_valid_job(), "attempt": -1})


def test_queue_job_missing_model_name() -> None:
    data = _valid_job()
    del data["model_name"]
    with pytest.raises(ValidationError):
        QueueJob(**data)


# ---------------------------------------------------------------------------
# ToolError
# ---------------------------------------------------------------------------

def test_tool_error_valid() -> None:
    e = ToolError(error="timeout", retryable=True)
    assert e.retryable is True


def test_tool_error_requires_retryable() -> None:
    with pytest.raises(ValidationError):
        ToolError(error="oops")  # missing retryable


# ---------------------------------------------------------------------------
# TriageAssessment
# ---------------------------------------------------------------------------

def test_triage_assessment_valid() -> None:
    t = TriageAssessment(
        drifting_features=["euribor3m"],
        drift_hypothesis="distribution_shift",
        recommended_actions=["retrain"],
        urgency="critical",
    )
    assert t.urgency == "critical"


def test_triage_assessment_rejects_bad_hypothesis() -> None:
    with pytest.raises(ValidationError):
        TriageAssessment(
            drifting_features=[],
            drift_hypothesis="aliens",
            recommended_actions=["monitor_only"],
            urgency="low",
        )


def test_triage_assessment_rejects_bad_urgency() -> None:
    with pytest.raises(ValidationError):
        TriageAssessment(
            drifting_features=[],
            drift_hypothesis="unknown",
            recommended_actions=["monitor_only"],
            urgency="extreme",
        )


# ---------------------------------------------------------------------------
# ActionDecision
# ---------------------------------------------------------------------------

def test_action_decision_valid() -> None:
    a = ActionDecision(
        chosen_action="replay_test",
        requires_human_approval=False,
        justification="warn severity, safe to auto-dispatch",
    )
    assert a.queue_job_id is None


def test_action_decision_rejects_bad_action() -> None:
    with pytest.raises(ValidationError):
        ActionDecision(
            chosen_action="nuke_production",
            requires_human_approval=True,
            justification="bad",
        )


# ---------------------------------------------------------------------------
# CommsReport
# ---------------------------------------------------------------------------

def test_comms_report_valid() -> None:
    r = CommsReport(
        summary="Drift resolved.",
        actions_taken=["replay_test"],
        next_steps="Monitor metrics.",
        investigation_status="resolved",
    )
    assert r.investigation_status == "resolved"


def test_comms_report_rejects_bad_status() -> None:
    with pytest.raises(ValidationError):
        CommsReport(
            summary="x",
            actions_taken=[],
            next_steps="y",
            investigation_status="pending",
        )


# ---------------------------------------------------------------------------
# HIL schemas
# ---------------------------------------------------------------------------

def test_hil_approval_request_valid() -> None:
    r = HILApprovalRequest(approved=True, approver_note="looks good")
    assert r.approved is True


def test_hil_approval_request_approved_false() -> None:
    r = HILApprovalRequest(approved=False)
    assert r.approved is False


def test_hil_approval_token_valid() -> None:
    t = HILApprovalToken(
        token="abc123",  # noqa: S106
        investigation_id="inv-001",
        issued_at=datetime.now(tz=UTC),
        action="retrain",
    )
    assert t.token == "abc123"  # noqa: S105


def test_hil_approval_token_missing_required() -> None:
    with pytest.raises(ValidationError):
        HILApprovalToken(token="abc123")  # noqa: S106  # missing investigation_id, issued_at, action


def test_investigation_summary_valid() -> None:
    now = datetime.now(tz=UTC)
    s = InvestigationSummary(
        investigation_id="inv-001",
        event_id="evt-001",
        severity="critical",
        model_name="bank_churn_classifier",
        model_version="1",
        status="open",
        started_at=now,
        updated_at=now,
    )
    assert s.status == "open"


def test_investigation_summary_rejects_bad_status() -> None:
    now = datetime.now(tz=UTC)
    with pytest.raises(ValidationError):
        InvestigationSummary(
            investigation_id="inv-001",
            event_id="evt-001",
            severity="critical",
            model_name="bank_churn_classifier",
            model_version="1",
            status="pending",
            started_at=now,
            updated_at=now,
        )
