import pytest
from pydantic import ValidationError

from app.schemas.prediction import PredictionRequest, PredictionResponse
from app.schemas.drift_report import DriftReportResponse, DriftWebhookPayload
from app.schemas.registry import ModelVersionInfo


VALID_PREDICTION = {
    "age": 35,
    "campaign": 2,
    "previous": 0,
    "pdays_contacted": 0,
    "emp_var_rate": -1.8,
    "cons_price_idx": 93.2,
    "cons_conf_idx": -42.0,
    "euribor3m": 1.3,
    "nr_employed": 5099.1,
    "job": "admin.",
    "marital": "married",
    "education": "university.degree",
    "default": "no",
    "housing": "yes",
    "loan": "no",
    "contact": "cellular",
    "month": "may",
    "day_of_week": "mon",
    "poutcome": "nonexistent",
}


class TestPredictionRequest:
    def test_valid_input_accepted(self):
        req = PredictionRequest(**VALID_PREDICTION)
        assert req.age == 35

    def test_age_below_minimum_rejected(self):
        with pytest.raises(ValidationError):
            PredictionRequest(**{**VALID_PREDICTION, "age": 10})

    def test_age_above_maximum_rejected(self):
        with pytest.raises(ValidationError):
            PredictionRequest(**{**VALID_PREDICTION, "age": 101})

    def test_campaign_below_minimum_rejected(self):
        with pytest.raises(ValidationError):
            PredictionRequest(**{**VALID_PREDICTION, "campaign": 0})

    def test_pdays_contacted_invalid_rejected(self):
        with pytest.raises(ValidationError):
            PredictionRequest(**{**VALID_PREDICTION, "pdays_contacted": 2})

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            PredictionRequest(**{**VALID_PREDICTION, "duration": 999})

    def test_missing_required_field_rejected(self):
        data = {k: v for k, v in VALID_PREDICTION.items() if k != "job"}
        with pytest.raises(ValidationError):
            PredictionRequest(**data)


class TestPredictionResponse:
    def test_valid_subscribed(self):
        resp = PredictionResponse(
            prediction_id="abc",
            label="subscribed",
            probability=0.8,
            model_version="4",
            threshold=0.37,
        )
        assert resp.label == "subscribed"

    def test_invalid_label_rejected(self):
        with pytest.raises(ValidationError):
            PredictionResponse(
                prediction_id="abc",
                label="maybe",
                probability=0.5,
                model_version="4",
                threshold=0.37,
            )


class TestDriftWebhookPayload:
    def test_valid_payload_accepted(self):
        payload = DriftWebhookPayload(
            severity="critical",
            previous_severity="warn",
            model_name="bank_churn_classifier",
            model_version="4",
            drift_report_id="some-uuid",
            psi_summary={"euribor3m": 0.35},
            chi2_summary={"month": 0.001},
            output_drift=0.18,
        )
        assert payload.event_type == "drift_alert"
        assert payload.webhook_version == "1.0"

    def test_event_id_auto_generated(self):
        p1 = DriftWebhookPayload(
            severity="ok", previous_severity="ok",
            model_name="m", model_version="1",
            drift_report_id="x", psi_summary={}, chi2_summary={}, output_drift=0.0,
        )
        p2 = DriftWebhookPayload(
            severity="ok", previous_severity="ok",
            model_name="m", model_version="1",
            drift_report_id="x", psi_summary={}, chi2_summary={}, output_drift=0.0,
        )
        assert p1.event_id != p2.event_id

    def test_missing_required_field_rejected(self):
        with pytest.raises(ValidationError):
            DriftWebhookPayload(severity="critical")


class TestModelVersionInfo:
    def test_valid_accepted(self):
        info = ModelVersionInfo(
            version="4",
            aliases=["production"],
            run_id="abc123",
            model_hash="deadbeef",
            training_date="2026-05-01T00:00:00",
            test_auc=0.81,
            test_recall=0.76,
            threshold=0.37,
        )
        assert info.version == "4"

    def test_missing_field_rejected(self):
        with pytest.raises(ValidationError):
            ModelVersionInfo(version="4", aliases=[])
