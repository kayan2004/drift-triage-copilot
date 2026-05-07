"""Shared HTTP client. All backend calls go through here.

Single source of truth so pages don't duplicate URL/error-handling logic.
Returns either parsed JSON or `None` (never raises) — pages render empty states.
"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx
import redis as redis_sync


MODEL_SERVICE_URL = os.environ.get("MODEL_SERVICE_URL", "http://localhost:8000")
AGENT_URL         = os.environ.get("AGENT_URL", "http://localhost:8001")
REDIS_URL         = os.environ.get("QUEUE_REDIS_URL", "redis://localhost:6379/1")

JOBS_KEY = "triage:jobs"
DLQ_KEY  = "triage:dlq"


# ── Generic ──────────────────────────────────────────────────────────────────

def _get(url: str, **kwargs: Any) -> Any:
    try:
        r = httpx.get(url, timeout=4.0, **kwargs)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _post(url: str, body: dict | None = None, **kwargs: Any) -> tuple[bool, Any]:
    try:
        r = httpx.post(url, json=body, timeout=20.0, **kwargs)
        if r.status_code in (200, 202):
            return True, r.json()
        try:
            return False, r.json().get("detail", r.text)
        except Exception:
            return False, r.text
    except Exception as exc:
        return False, str(exc)


# ── Health ───────────────────────────────────────────────────────────────────

def model_service_healthy() -> bool:
    h = _get(f"{MODEL_SERVICE_URL}/health")
    return bool(h and h.get("status") == "ok")


def agent_healthy() -> bool:
    h = _get(f"{AGENT_URL}/health")
    return bool(h and h.get("status") == "ok")


# ── Predictions / Drift ──────────────────────────────────────────────────────

def send_prediction(payload: dict) -> bool:
    ok, _ = _post(f"{MODEL_SERVICE_URL}/predict/", payload)
    return ok


def send_batch(profile: str, n: int) -> tuple[bool, str]:
    ok, result = _post(f"{MODEL_SERVICE_URL}/demo/batch/{profile}", params={"n": n})
    if ok:
        return True, f"{n} {profile} predictions sent."
    return False, str(result)


def prediction_count() -> int:
    result = _get(f"{MODEL_SERVICE_URL}/predict/count")
    return (result or {}).get("count", 0)


def compute_drift() -> tuple[bool, dict | str]:
    return _post(f"{MODEL_SERVICE_URL}/drift/compute")


def latest_drift_report() -> dict | None:
    return _get(f"{MODEL_SERVICE_URL}/drift/report")


# ── Registry ─────────────────────────────────────────────────────────────────

def list_versions() -> list[dict]:
    return _get(f"{MODEL_SERVICE_URL}/registry/versions") or []


# ── Investigations ───────────────────────────────────────────────────────────

def list_investigations(status: str | None = None) -> list[dict]:
    params = {"status": status} if status else None
    return _get(f"{AGENT_URL}/investigations/", params=params) or []


def get_investigation(inv_id: str) -> dict | None:
    return _get(f"{AGENT_URL}/investigations/{inv_id}")


def approve_investigation(inv_id: str, note: str, approved: bool = True) -> tuple[bool, str]:
    body = {"approved": approved, "approver_note": note}
    ok, result = _post(f"{AGENT_URL}/investigations/{inv_id}/approve", body)
    if ok:
        return True, "Action dispatched." if approved else "Rejected."
    return False, str(result)


# ── Redis (queue / DLQ) ──────────────────────────────────────────────────────

def _redis() -> redis_sync.Redis:
    return redis_sync.from_url(REDIS_URL, decode_responses=True)


def queue_depths() -> tuple[int, int]:
    try:
        r = _redis()
        jobs = r.llen(JOBS_KEY)
        dlq = r.llen(DLQ_KEY)
        r.close()
        return jobs, dlq
    except redis_sync.RedisError:
        return 0, 0


def dlq_items(count: int = 25) -> list[dict]:
    try:
        r = _redis()
        raw = r.lrange(DLQ_KEY, 0, count - 1)
        r.close()
        out = []
        for item in raw:
            try:
                out.append(json.loads(item))
            except (json.JSONDecodeError, ValueError):
                out.append({"raw": item})
        return out
    except redis_sync.RedisError:
        return []


def dlq_retry(job_id: str) -> bool:
    try:
        r = _redis()
        for raw in r.lrange(DLQ_KEY, 0, -1):
            try:
                job = json.loads(raw)
                if job.get("job_id") == job_id:
                    job.pop("dlq_error", None)
                    job["attempt"] = 0
                    r.lrem(DLQ_KEY, 1, raw)
                    r.lpush(JOBS_KEY, json.dumps(job))
                    r.close()
                    return True
            except (json.JSONDecodeError, ValueError):
                continue
        r.close()
        return False
    except redis_sync.RedisError:
        return False


def dlq_dismiss(job_id: str) -> bool:
    try:
        r = _redis()
        for raw in r.lrange(DLQ_KEY, 0, -1):
            try:
                job = json.loads(raw)
                if job.get("job_id") == job_id:
                    r.lrem(DLQ_KEY, 1, raw)
                    r.close()
                    return True
            except (json.JSONDecodeError, ValueError):
                continue
        r.close()
        return False
    except redis_sync.RedisError:
        return False


# ── Demo reset ───────────────────────────────────────────────────────────────

def reset_demo() -> tuple[bool, str]:
    """Clear all runtime data across both services and Redis.

    Calls model_service /demo/reset (predictions + drift_reports) and
    agent /demo/reset (investigations + LangGraph checkpoints), then flushes
    the Redis job queues. The MLflow model registry is never touched.
    """
    ms_ok, ms_err = _post(f"{MODEL_SERVICE_URL}/demo/reset")
    ag_ok, ag_err = _post(f"{AGENT_URL}/demo/reset")
    try:
        r = _redis()
        r.delete(JOBS_KEY, DLQ_KEY, "triage:seen_jobs")
        r.close()
    except Exception:
        pass
    if ms_ok and ag_ok:
        return True, "Reset complete — predictions, drift reports, investigations, checkpoints and queue cleared."
    errors = []
    if not ms_ok:
        errors.append(f"model_service: {ms_err}")
    if not ag_ok:
        errors.append(f"agent: {ag_err}")
    return False, " | ".join(errors)


# ── Demo payloads ────────────────────────────────────────────────────────────
# Normal  → severity ok,       no investigation
# Mild    → severity warn,     urgency medium → replay_test, no HIL, auto-resolves
# Drifted → severity critical, urgency critical → retrain, HIL required

NORMAL_PAYLOAD = {
    "age": 35, "job": "technician", "marital": "single",
    "education": "university.degree", "default": "no", "housing": "yes",
    "loan": "no", "contact": "cellular", "month": "jun", "day_of_week": "thu",
    "campaign": 2, "pdays_contacted": 1, "previous": 1, "poutcome": "success",
    "emp_var_rate": -1.8, "cons_price_idx": 93.075, "cons_conf_idx": -36.4,
    "euribor3m": 0.887, "nr_employed": 5099.1,
}

# Mild drift: age skews older, more campaign contacts, telephone instead of cellular.
# Economic indicators unchanged. Produces PSI ~0.12-0.18 (warn zone) not critical.
MILD_PAYLOAD = {
    "age": 52, "job": "admin.", "marital": "married",
    "education": "high.school", "default": "no", "housing": "yes",
    "loan": "no", "contact": "telephone", "month": "aug", "day_of_week": "mon",
    "campaign": 5, "pdays_contacted": 0, "previous": 0, "poutcome": "nonexistent",
    "emp_var_rate": -1.8, "cons_price_idx": 93.075, "cons_conf_idx": -36.4,
    "euribor3m": 0.887, "nr_employed": 5099.1,
}

DRIFTED_PAYLOAD = {
    "age": 75, "job": "retired", "marital": "divorced",
    "education": "basic.4y", "default": "unknown", "housing": "unknown",
    "loan": "unknown", "contact": "telephone", "month": "dec", "day_of_week": "fri",
    "campaign": 15, "pdays_contacted": 0, "previous": 0, "poutcome": "nonexistent",
    "emp_var_rate": 1.4, "cons_price_idx": 94.465, "cons_conf_idx": -41.8,
    "euribor3m": 4.962, "nr_employed": 5228.1,
}
