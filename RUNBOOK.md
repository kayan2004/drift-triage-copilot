# RUNBOOK.md — Operational Guide

---

## Starting the Stack

```bash
# First time only
cp .env.example .env
# Fill in: ANTHROPIC_API_KEY, WEBHOOK_SECRET (any random string)

# Start all services
docker-compose up --build

# Wait for all healthchecks to pass (~60s)
docker-compose ps

# Train and register the model (run once after first start, or after reset)
docker-compose run --rm model_service uv run python -m training.train
```

Services become available at:
- Model service: http://localhost:8000/docs
- Agent: http://localhost:8001/docs
- MLflow: http://localhost:5000
- Dashboard: http://localhost:8501

---

## Running Tests

```bash
# Agent tests (LLM mocked — no API key needed)
cd agent && uv run pytest tests/ -q

# Model service tests
cd model_service && uv run pytest tests/ -q

# Lint
cd agent && uvx ruff check .
cd model_service && uvx ruff check .
```

---

## Triggering a Manual Drift Check

```bash
curl -X POST http://localhost:8000/drift/compute
```

This pulls the last 500 predictions, computes PSI + chi2 + output drift, stores a `DriftReport`, and emits a webhook to the agent if severity changed.

To inject artificial drift, send predictions with shifted feature values before running the compute:

```bash
# Example: shift euribor3m distribution upward
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"age": 45, "job": "management", "marital": "married", "education": "university.degree",
       "default": "no", "housing": "yes", "loan": "no", "contact": "cellular",
       "month": "may", "day_of_week": "mon", "campaign": 1, "pdays_contacted": 0,
       "previous": 0, "poutcome": "nonexistent", "emp_var_rate": 1.4,
       "cons_price_idx": 93.994, "cons_conf_idx": -36.4, "euribor3m": 4.857,
       "nr_employed": 5191.0}'
```

---

## Approving a HIL Request

1. Open the dashboard: http://localhost:8501
2. Navigate to **HIL Inbox**
3. Review the triage assessment and proposed action
4. Click **Approve** or **Reject**

Or via API:

```bash
# List investigations awaiting approval
curl http://localhost:8001/investigations/?status=awaiting_approval

# Approve
curl -X POST http://localhost:8001/investigations/{investigation_id}/approve \
  -H "Content-Type: application/json" \
  -d '{"approved": true, "approver_note": "Drift confirmed, proceed with retrain"}'

# Reject
curl -X POST http://localhost:8001/investigations/{investigation_id}/approve \
  -H "Content-Type: application/json" \
  -d '{"approved": false, "approver_note": "Data pipeline issue, not real drift"}'
```

---

## Retrying a DLQ Job

Jobs land in the DLQ (`triage:dlq`) after 3 failed attempts.

```bash
# View DLQ contents
curl http://localhost:8001/queue/dlq

# Requeue a specific job
curl -X POST http://localhost:8001/queue/dlq/{job_id}/requeue

# Dismiss (delete) a job from DLQ
curl -X DELETE http://localhost:8001/queue/dlq/{job_id}
```

Or via the dashboard: **Queue Monitor** → DLQ table → Retry / Dismiss buttons.

---

## Running Database Migrations

```bash
# Agent migrations
cd agent && uv run alembic upgrade head

# Model service migrations
cd model_service && uv run alembic upgrade head

# Generate a new migration after changing ORM models
cd agent && uv run alembic revision --autogenerate -m "describe change"
```

---

## Rolling Back the Model Manually

The queue worker handles rollback jobs automatically. To trigger manually:

```bash
# Via the agent queue (recommended — idempotency enforced)
curl -X POST http://localhost:8001/investigations/{investigation_id}/approve \
  -H "Content-Type: application/json" \
  -d '{"approved": true, "approver_note": "Manual rollback"}'

# Direct MLflow alias change (break-glass only — bypasses HIL gate)
# cd model_service
# uv run python -c "
# import mlflow
# client = mlflow.MlflowClient('http://localhost:5000')
# client.set_registered_model_alias('bank_churn_classifier', 'staging', '<previous_version>')
# "
```

---

## Checking Service Health

```bash
curl http://localhost:8000/health   # model_service
curl http://localhost:8001/health   # agent
```

Both return `{"status": "ok"}` when healthy.

---

## Viewing Logs

```bash
# All services
docker-compose logs -f

# Single service
docker-compose logs -f agent
docker-compose logs -f queue_worker
docker-compose logs -f model_service
```

Logs are structured JSON (structlog). Key fields to watch:

| Field | Meaning |
|---|---|
| `investigation_id` | Ties all events for one drift investigation |
| `event` | Node name (e.g. `triage_agent.complete`) |
| `severity` | Drift severity at time of event |
| `job_id` | Queue job identifier |
| `attempt` | Queue retry attempt number |

---

## Common Failure Modes

### Agent won't start — `AsyncPostgresSaver.setup()` fails
**Cause:** Postgres not ready or `AGENT_DATABASE_URL` wrong.
**Fix:** Check `docker-compose ps` for postgres health. Verify `.env` has correct `AGENT_DATABASE_URL`.

### Investigation stuck in `open` status
**Cause:** LangGraph graph raised an unhandled exception mid-run.
**Fix:** Check `docker-compose logs agent` for the `investigation_id`. The webhook route catches exceptions and sets status to `escalated` — if it's still `open`, the background task is still running. Wait or restart the agent (it will resume from checkpoint).

### Queue job stuck — keeps retrying
**Cause:** Transient error exceeding backoff window, or model_service unreachable.
**Fix:** Check `docker-compose logs queue_worker`. If model_service is down, bring it back up — the worker will retry. If the job is legitimately broken, let it exhaust retries and land in DLQ, then dismiss it.

### DLQ growing — jobs not being processed
**Cause:** Worker crashed, or `max_attempts` exhausted on genuine errors.
**Fix:** `docker-compose logs queue_worker`. Restart worker: `docker-compose restart queue_worker`. Review DLQ jobs in dashboard and requeue or dismiss.

### MLflow not accessible at startup
**Cause:** `mlflow` container not healthy when model_service starts.
**Fix:** `docker-compose` healthchecks handle this — model_service waits for mlflow. If it still fails, run: `docker-compose restart model_service`.

### LangGraph checkpoint resume not working
**Cause:** `thread_id` mismatch — a new `event_id` was generated for the same logical event.
**Fix:** The webhook sender (model_service) must use the same `event_id` for retries. Check that drift report IDs are stable and not regenerated on retry.
