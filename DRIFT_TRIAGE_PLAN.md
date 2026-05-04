# DRIFT TRIAGE CO-PILOT — MASTER IMPLEMENTATION PLAN
# Week 5 | AIE Bootcamp | Paste this into Claude Code (VS Code)

---

## HOW TO USE THIS PLAN
Paste this entire document into Claude Code in VS Code.
Work phase by phase. Do not skip ahead. Each phase produces working, committed code before the next begins.
Engineering rules from P4-notes apply everywhere: uv, async, Pydantic at every boundary, structlog, Depends(), lifespan singletons, no os.getenv() outside Settings, conventional commits.

---

## REPOSITORY LAYOUT (build toward this from Phase 0)

```
drift-triage/
├── model_service/              # FastAPI — predictions, drift, registry, webhooks
│   ├── app/
│   │   ├── main.py             # FastAPI app + lifespan only
│   │   ├── config.py           # Settings (pydantic-settings)
│   │   ├── dependencies.py     # Depends() factories
│   │   ├── routes/
│   │   │   ├── predict.py
│   │   │   ├── drift.py
│   │   │   ├── registry.py
│   │   │   └── webhook.py
│   │   ├── services/
│   │   │   ├── model_loader.py
│   │   │   ├── drift_calculator.py
│   │   │   ├── promotion_gate.py
│   │   │   └── prediction_store.py
│   │   ├── schemas/
│   │   │   ├── prediction.py
│   │   │   ├── drift_report.py
│   │   │   └── registry.py
│   │   └── db/
│   │       ├── session.py
│   │       └── models.py
│   ├── migrations/             # Alembic
│   ├── pyproject.toml
│   ├── uv.lock
│   └── Dockerfile
├── agent/                      # LangGraph supervisor + sub-agents
│   ├── app/
│   │   ├── main.py             # FastAPI webhook receiver + HIL endpoint
│   │   ├── config.py
│   │   ├── dependencies.py
│   │   ├── graph/
│   │   │   ├── supervisor.py
│   │   │   ├── triage_agent.py
│   │   │   ├── action_agent.py
│   │   │   └── comms_agent.py
│   │   ├── tools/
│   │   │   ├── replay_test.py
│   │   │   ├── retrain_model.py
│   │   │   ├── rollback_model.py
│   │   │   └── fetch_drift_report.py
│   │   ├── prompts/            # Prompts as files, never inline strings
│   │   │   ├── supervisor.md
│   │   │   ├── triage.md
│   │   │   ├── action.md
│   │   │   └── comms.md
│   │   ├── queue/
│   │   │   ├── producer.py
│   │   │   └── worker.py
│   │   └── schemas/
│   │       ├── webhook.py
│   │       ├── tool_io.py
│   │       └── hil.py
│   ├── tests/
│   │   ├── fixtures/           # Snapshot trajectory JSON fixtures
│   │   ├── test_supervisor_routing.py
│   │   └── test_tool_schemas.py
│   ├── pyproject.toml
│   ├── uv.lock
│   └── Dockerfile
├── dashboard/                  # Streamlit
│   ├── app.py
│   ├── pages/
│   │   ├── registry.py
│   │   ├── investigations.py
│   │   ├── queue_monitor.py
│   │   └── hil_inbox.py
│   ├── pyproject.toml
│   ├── uv.lock
│   └── Dockerfile
├── training/                   # Notebooks + training script (not in prod image)
│   ├── train.py
│   ├── evaluate.py
│   └── exploration.ipynb
├── .github/
│   └── workflows/
│       └── ci.yml
├── docker-compose.yml
├── .env.example
├── ARCH.md
├── DECISIONS.md
└── RUNBOOK.md
```

---

## PHASE 0 — REPO BOOTSTRAP (≈30 min)

### Goal
Empty repo → working skeleton with uv, git, pre-commit, and docker-compose shell in place.

### Steps

**0.1 Init repo and top-level structure**
```bash
git init drift-triage && cd drift-triage
mkdir -p model_service/app/{routes,services,schemas,db} \
         model_service/migrations \
         agent/app/{graph,tools,prompts,queue,schemas} \
         agent/tests/fixtures \
         dashboard/pages \
         training \
         .github/workflows
```

**0.2 Create .gitignore (commit zero)**
```
.env
.env.*
.venv/
venv/
__pycache__/
*.py[cod]
*.egg-info/
.DS_Store
mlruns/
*.pem
*.key
```

**0.3 Create .env.example**
```dotenv
# Model Service
OPENAI_API_KEY=sk-...
DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/drift_triage
MLFLOW_TRACKING_URI=http://mlflow:5000
MODEL_NAME=bank_churn_classifier
REDIS_URL=redis://redis:6379/0
WEBHOOK_SECRET=changeme

# Agent
AGENT_DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/agent_checkpoints
MODEL_SERVICE_URL=http://model_service:8000
ANTHROPIC_API_KEY=sk-ant-...

# Dashboard
MODEL_SERVICE_URL=http://model_service:8000
AGENT_URL=http://agent:8001
```

**0.4 Pre-commit config**
Create `.pre-commit-config.yaml`:
```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.5.0
    hooks:
      - id: ruff
      - id: ruff-format
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.0
    hooks:
      - id: gitleaks
```

**0.5 pyproject.toml per service (model_service example)**
```toml
[project]
name = "model-service"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.29",
    "pydantic>=2.7",
    "pydantic-settings>=2.2",
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg>=0.29",
    "alembic>=1.13",
    "httpx>=0.27",
    "tenacity>=8.3",
    "mlflow>=2.12",
    "scikit-learn>=1.4",
    "scipy>=1.13",
    "pandas>=2.2",
    "structlog>=24.1",
    "cachetools>=5.3",
    "redis>=5.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.1", "pytest-asyncio>=0.23", "ruff>=0.5"]

[tool.ruff]
line-length = 100
target-version = "py312"
select = ["E", "F", "I", "B", "UP", "ASYNC", "S"]
```

**0.6 docker-compose.yml shell**
```yaml
version: "3.9"
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: drift_triage
    volumes:
      - postgres_data:/var/lib/postgresql/data
    networks: [triage_net]

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data
    networks: [triage_net]

  mlflow:
    image: ghcr.io/mlflow/mlflow:v2.12.1
    command: mlflow server --host 0.0.0.0 --port 5000 --backend-store-uri /mlruns
    volumes:
      - mlflow_data:/mlruns
    networks: [triage_net]
    ports: ["5000:5000"]

  model_service:
    build: ./model_service
    env_file: .env
    depends_on: [postgres, redis, mlflow]
    networks: [triage_net]
    ports: ["8000:8000"]

  agent:
    build: ./agent
    env_file: .env
    depends_on: [postgres, redis, model_service]
    networks: [triage_net]
    ports: ["8001:8001"]

  queue_worker:
    build: ./agent
    command: python -m app.queue.worker
    env_file: .env
    depends_on: [redis, model_service]
    networks: [triage_net]

  dashboard:
    build: ./dashboard
    env_file: .env
    depends_on: [model_service, agent]
    networks: [triage_net]
    ports: ["8501:8501"]

volumes:
  postgres_data:
  redis_data:
  mlflow_data:

networks:
  triage_net:
```

**0.7 First commit**
```bash
git add .
git commit -m "chore(repo): bootstrap structure, gitignore, pre-commit, compose shell"
```

---

## PHASE 1 — DATASET & MODEL TRAINING (≈2 hours)

### Goal
Trained scikit-learn pipeline registered in MLflow with the full artifact triple. A `training/train.py` script that is reproducible and runnable standalone.

### Steps

**1.1 Download dataset**
```bash
# Place bank-additional-full.csv in training/data/ (add data/*.csv to .gitignore)
```

**1.2 Create `training/train.py`**

This script must:
- Load `bank-additional-full.csv`
- Drop `duration` column immediately after load (data leakage — it's only known after the call ends)
- Encode `pdays`: create `pdays_was_contacted` boolean flag (1 if pdays != 999, else 0), then drop raw `pdays` or bin it
- Leave `unknown` as a real category value — do NOT impute or treat as NaN
- Stratified 60/20/20 split with `random_state=42`
- Build a `Pipeline(steps=[("preprocessor", ColumnTransformer(...)), ("classifier", ...)])`
  - Numerics: `StandardScaler`
  - Categoricals: `OneHotEncoder(handle_unknown="ignore")` — this handles any unseen category at inference including 'unknown'
- Train and tune operating threshold: iterate thresholds from 0.5 down to 0.01 in steps of 0.01, pick the HIGHEST threshold where recall on the validation set >= 0.75
- Log to MLflow: params (model type, hyperparams, threshold), metrics (AUC, F1, precision, recall at operating threshold on test set), artifacts:
  1. `model.pkl` — the fitted pipeline (via `mlflow.sklearn.log_model`)
  2. `schema.json` — feature names and types
  3. `model_card.json` — {model_hash (sha256 of model.pkl), python_version, sklearn_version, training_date, dataset_rows, threshold, test_auc, test_f1, test_recall, test_precision}
- Register model as `MODEL_NAME` version, set alias `staging`
- Save reference statistics for drift detection: mean/std per numeric feature, value_counts per categorical feature, output distribution — to `training/reference_stats.json`

```python
# training/train.py skeleton (Claude Code: implement fully)

import hashlib, json, os
from pathlib import Path
import numpy as np
import pandas as pd
import mlflow
import mlflow.sklearn
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import (
    roc_auc_score, f1_score, precision_score, recall_score, classification_report
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
import joblib

RANDOM_STATE = 42
TARGET = "y"
DROP_COLS = ["duration"]  # leaks target — drop first
PDAYS_SENTINEL = 999

def load_and_clean(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";")
    df = df.drop(columns=DROP_COLS)
    # bin pdays sentinel into a flag
    df["pdays_contacted"] = (df["pdays"] != PDAYS_SENTINEL).astype(int)
    df = df.drop(columns=["pdays"])
    df[TARGET] = (df[TARGET] == "yes").astype(int)
    return df

def tune_threshold(model: Pipeline, X_val: pd.DataFrame, y_val: pd.Series) -> float:
    """Highest threshold where recall >= 0.75 on validation set."""
    probs = model.predict_proba(X_val)[:, 1]
    best_threshold = 0.5
    for t in np.arange(0.95, 0.00, -0.01):
        preds = (probs >= t).astype(int)
        if recall_score(y_val, preds, zero_division=0) >= 0.75:
            best_threshold = round(t, 2)
            break
    return best_threshold

def compute_reference_stats(df: pd.DataFrame, numeric_cols: list, cat_cols: list) -> dict:
    stats = {
        "numerics": {
            col: {"mean": df[col].mean(), "std": df[col].std()}
            for col in numeric_cols
        },
        "categoricals": {
            col: df[col].value_counts(normalize=True).to_dict()
            for col in cat_cols
        },
        "output": {"positive_rate": df[TARGET].mean()},
    }
    return stats

if __name__ == "__main__":
    # Claude Code: implement full training loop following the skeleton above
    # Set mlflow.set_tracking_uri from env or default to http://localhost:5000
    # Run load_and_clean, split, train pipeline, tune_threshold, log everything to MLflow
    # Write reference_stats.json to training/
    pass
```

**Classifier recommendation**: `GradientBoostingClassifier` or `HistGradientBoostingClassifier` — handles mixed types well, strong on imbalanced data. If you use `HistGradientBoostingClassifier`, it has native categorical support (set `categorical_features`), which avoids the OHE step for categoricals.

**1.3 Run training**
```bash
cd training
uv run python train.py
```

Verify in MLflow UI (localhost:5000) that model is registered with all 3 artifacts and alias `staging`.

**1.4 Commit**
```bash
git add training/
git commit -m "feat(training): train bank marketing classifier, register in MLflow with artifact triple"
```

---

## PHASE 2 — MODEL SERVICE — CORE API (≈3 hours)

### Goal
FastAPI service that loads the model from MLflow, serves predictions with Pydantic validation, stores predictions in Postgres, and exposes registry state.

### Steps

**2.1 `model_service/app/config.py`**
```python
from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="forbid")

    database_url: str
    mlflow_tracking_uri: str
    model_name: str = "bank_churn_classifier"
    redis_url: str
    webhook_secret: str
    log_level: str = "INFO"

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
```

**2.2 `model_service/app/db/models.py`**
SQLAlchemy async models:
- `Prediction`: id, created_at, input_features (JSONB), probability, label, model_version, threshold
- `DriftReport`: id, created_at, window_start, window_end, severity (enum: ok/warn/critical), psi_scores (JSONB), chi2_scores (JSONB), output_drift (float), raw_report (JSONB)
- `ModelVersion`: id, name, version, alias, registered_at, model_hash, is_active

**2.3 `model_service/app/db/session.py`**
```python
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from app.config import get_settings

def make_engine():
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)

def make_session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
```

**2.4 `model_service/app/services/model_loader.py`**
```python
# Loads the model from MLflow by alias "production" (falls back to "staging" if no production alias)
# Returns the fitted pipeline + the operating threshold from the model card
# This is attached to app.state in lifespan — never loaded per-request
```

**2.5 `model_service/app/schemas/prediction.py`**
```python
from pydantic import BaseModel, Field
from typing import Literal

# All 20 features minus duration minus pdays plus pdays_contacted flag
# Every field typed, categoricals use Literal where enum is known
class PredictionRequest(BaseModel):
    age: int = Field(..., ge=18, le=100)
    job: str          # 'unknown' is valid — do NOT reject it
    marital: str
    education: str
    default: str
    housing: str
    loan: str
    contact: str
    month: str
    day_of_week: str
    campaign: int = Field(..., ge=1)
    pdays_contacted: int = Field(..., ge=0, le=1)
    previous: int = Field(..., ge=0)
    poutcome: str
    emp_var_rate: float
    cons_price_idx: float
    cons_conf_idx: float
    euribor3m: float
    nr_employed: float

class PredictionResponse(BaseModel):
    prediction_id: str
    label: Literal["subscribed", "not_subscribed"]
    probability: float
    model_version: str
    threshold: float
```

**2.6 `model_service/app/routes/predict.py`**
```python
from fastapi import APIRouter, Depends, HTTPException
from app.schemas.prediction import PredictionRequest, PredictionResponse
from app.dependencies import get_model, get_db_session
# ...

router = APIRouter(prefix="/predict", tags=["predictions"])

@router.post("/", response_model=PredictionResponse, status_code=200)
async def predict(
    body: PredictionRequest,
    model_bundle=Depends(get_model),
    session=Depends(get_db_session),
) -> PredictionResponse:
    # Convert body to DataFrame (one row), run model.predict_proba
    # Apply threshold from model_bundle
    # Store to predictions table
    # Return PredictionResponse
    ...
```

**2.7 `model_service/app/routes/registry.py`**
Endpoints:
- `GET /registry/versions` — list all registered model versions
- `GET /registry/versions/{version}` — get one version details
- `POST /registry/promote/{version}` — promote to Production after running promotion gate

**2.8 `model_service/app/services/promotion_gate.py`**
```python
# The promotion checklist (programmatic gate — must all pass before Production alias is set):
# 1. test_auc >= 0.75
# 2. test_recall >= 0.75 (at operating threshold)
# 3. model_card.json exists and hash matches the registered binary
# 4. No active critical drift alert
# 5. Human approval token present (passed from agent HIL flow)
#
# If any check fails: raise HTTPException(status_code=422, detail=<specific failure>)
# If all pass: set "production" alias in MLflow registry
```

**2.9 `model_service/app/main.py`**
```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.config import get_settings
from app.services.model_loader import load_model_bundle
from app.db.session import make_engine, make_session_factory
from app.routes import predict, drift, registry, webhook
import structlog

log = structlog.get_logger()

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.engine = make_engine()
    app.state.session_factory = make_session_factory(app.state.engine)
    app.state.model_bundle = await load_model_bundle(settings)
    log.info("model_service.startup.complete", model=settings.model_name)
    yield
    await app.state.engine.dispose()

app = FastAPI(title="Drift Triage — Model Service", lifespan=lifespan)
app.include_router(predict.router)
app.include_router(drift.router)
app.include_router(registry.router)
app.include_router(webhook.router)
```

**2.10 Alembic setup**
```bash
cd model_service
uv run alembic init migrations
# Edit alembic.ini to use DATABASE_URL from env
# Edit migrations/env.py to import your Base and use async engine
uv run alembic revision --autogenerate -m "initial schema"
uv run alembic upgrade head
```

**2.11 Dockerfile (model_service)**
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY app/ ./app/
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**2.12 Commit**
```bash
git commit -m "feat(model-service): add predict, registry routes, DB models, lifespan singletons"
```

---

## PHASE 3 — DRIFT DETECTION ENGINE (≈2 hours)

### Goal
Rolling-window drift reports using PSI for numerics and chi2 for categoricals. Severity classification. Webhook emission.

### Steps

**3.1 `model_service/app/services/drift_calculator.py`**

```python
# PSI (Population Stability Index) for numeric features:
# PSI = sum((actual_pct - expected_pct) * ln(actual_pct / expected_pct))
# Buckets: 10 equal-width bins based on reference distribution
# Severity thresholds: PSI < 0.1 = ok, 0.1-0.2 = warn, > 0.2 = critical

# Chi-squared test for categorical features:
# scipy.stats.chi2_contingency on observed vs reference counts
# Severity: p_value > 0.05 = ok, 0.01-0.05 = warn, < 0.01 = critical

# Output drift: absolute difference in positive prediction rate vs reference
# Threshold: > 0.05 = warn, > 0.10 = critical

# Overall severity = max severity across all features + output

def compute_psi(reference: np.ndarray, current: np.ndarray, bins: int = 10) -> float: ...
def compute_chi2_pvalue(reference_counts: dict, current_counts: dict) -> float: ...
def classify_severity(psi_scores: dict, chi2_pvalues: dict, output_drift: float) -> str: ...
```

**3.2 `model_service/app/routes/drift.py`**
```python
# GET /drift/report — latest drift report
# GET /drift/report/history?limit=10 — last N reports
# POST /drift/compute — trigger manual drift computation (used by queue worker)

# Background task: run drift computation every N minutes (configurable via settings)
# Use asyncio background task or APScheduler — NOT blocking
```

**3.3 Drift report computation flow**
1. Pull last `drift_window_size` predictions from DB (default: 500, configurable in Settings)
2. Extract feature columns from stored `input_features` JSONB
3. Compare against `reference_stats.json` loaded at startup
4. Compute PSI per numeric, chi2 p-value per categorical, output drift
5. Classify overall severity
6. Store `DriftReport` to DB
7. If severity changed since last report → emit webhook to agent

**3.4 `model_service/app/routes/webhook.py`**
```python
# POST /webhooks/drift — internal route: emit outbound webhook to agent
# Payload schema (this is the contract — version it):
class DriftWebhookPayload(BaseModel):
    event_id: str          # uuid4
    event_type: Literal["drift_alert"]
    timestamp: datetime
    severity: Literal["ok", "warn", "critical"]
    previous_severity: Literal["ok", "warn", "critical"]
    model_name: str
    model_version: str
    drift_report_id: str
    psi_summary: dict      # {feature: psi_value}
    chi2_summary: dict     # {feature: p_value}
    output_drift: float
    webhook_version: str = "1.0"   # bump this on breaking changes
```

Emit via `httpx.AsyncClient` with retry (tenacity), HMAC-SHA256 signature in `X-Webhook-Signature` header using `settings.webhook_secret`. The agent verifies this signature.

**3.5 Load reference stats in lifespan**
```python
# In model_service lifespan, load training/reference_stats.json
# Attach to app.state.reference_stats
# This is the baseline for all drift comparisons
```

**3.6 Commit**
```bash
git commit -m "feat(drift): PSI + chi2 drift engine, severity classification, webhook emission"
```

---

## PHASE 4 — LANGGRAPH SUPERVISOR AGENT (≈4 hours)

### Goal
Three sub-agents under a supervisor. Postgres checkpoints. HIL pause. Prompts as files.

### Steps

**4.1 `agent/app/config.py`** — same pattern as model_service Settings

**4.2 Prompt files** — create these before writing agent code
```
agent/app/prompts/supervisor.md
agent/app/prompts/triage.md
agent/app/prompts/action.md
agent/app/prompts/comms.md
```

Each file has: `# SYSTEM PROMPT\n<role and constraints>\n---\n# USER PROMPT TEMPLATE\n<template with {variables}>`

Example `triage.md`:
```markdown
# SYSTEM PROMPT
You are the Triage Agent in a drift monitoring system for an ML model serving bank marketing predictions.
Your role: analyze a drift report and produce a structured assessment.
Output format: always JSON matching TriageAssessment schema.
Constraints: never recommend Production actions — escalate to Action Agent.

# USER PROMPT TEMPLATE
Drift event received at {timestamp}.
Severity: {severity} (previous: {previous_severity})
PSI scores: {psi_summary}
Chi2 p-values: {chi2_summary}
Output drift: {output_drift}
Current model: {model_name} v{model_version}

Assess: which features are drifting most severely? Is this likely data quality, distribution shift, or seasonal? What actions should be considered?
```

**4.3 `agent/app/schemas/tool_io.py`**
```python
from pydantic import BaseModel
from typing import Literal

class ToolError(BaseModel):
    error: str
    retryable: bool

class TriageAssessment(BaseModel):
    drifting_features: list[str]
    drift_hypothesis: str
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
```

**4.4 `agent/app/graph/supervisor.py`**

```python
# LangGraph StateGraph with:
# State: {
#   drift_event: DriftWebhookPayload,
#   triage_result: TriageAssessment | None,
#   action_decision: ActionDecision | None,
#   hil_approved: bool,
#   comms_result: CommsReport | None,
#   messages: list,
# }
#
# Nodes: supervisor, triage_agent, action_agent, comms_agent
# Edges:
#   START -> supervisor
#   supervisor -> triage_agent (always first)
#   supervisor -> action_agent (after triage)
#   supervisor -> INTERRUPT (if action requires HIL)
#   supervisor -> action_agent (after HIL approved)
#   supervisor -> comms_agent (after action dispatched)
#   supervisor -> END
#
# Persistence: PostgresSaver from langgraph-checkpoint-postgres
# Thread ID = drift_event.event_id (one thread per investigation)
```

```python
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import interrupt

# Load prompt from file — never inline
def load_prompt(name: str) -> str:
    return (Path(__file__).parent.parent / "prompts" / f"{name}.md").read_text()

SUPERVISOR_PROMPT = load_prompt("supervisor")
```

**4.5 `agent/app/graph/triage_agent.py`**
```python
# Calls Claude (structured output → TriageAssessment)
# Calls fetch_drift_report tool to get full report from model service
# Returns TriageAssessment — never raises, wraps errors in ToolError
```

**4.6 `agent/app/graph/action_agent.py`**
```python
# Reads TriageAssessment, decides action
# If action touches Production: set requires_human_approval=True, return — supervisor will INTERRUPT
# If monitor_only or replay_test: dispatch to Redis queue directly
# Returns ActionDecision
```

**4.7 `agent/app/graph/comms_agent.py`**
```python
# Summarizes the full investigation into CommsReport
# Sends structured summary (log it, store it, emit to dashboard via DB)
```

**4.8 HIL flow**
```python
# In supervisor: if action_decision.requires_human_approval:
#     interrupt("Awaiting human approval")
# Dashboard polls GET /agent/investigations/{id}/pending_approvals
# Human clicks Approve/Reject in dashboard → POST /agent/investigations/{id}/approve
# Agent resumes from checkpoint at the interrupt point
```

**4.9 `agent/app/main.py`**
```python
# FastAPI with two endpoints:
# POST /webhooks/drift — receives drift alert from model service
#   - Verify HMAC signature
#   - Start new LangGraph thread with event as input
#   - Return 202 Accepted immediately (async — don't block on agent run)
# POST /investigations/{id}/approve — HIL approval
#   - Resume LangGraph thread from checkpoint
# GET /investigations — list all open/resolved investigations
# GET /investigations/{id} — investigation detail + trajectory
```

**4.10 Commit**
```bash
git commit -m "feat(agent): LangGraph supervisor + 3 sub-agents, Postgres checkpoints, HIL interrupt"
```

---

## PHASE 5 — REDIS QUEUE & WORKER (≈2 hours)

### Goal
Slow tools (replay_test, retrain, rollback) dispatched through Redis with idempotency keys, exponential backoff, DLQ.

### Steps

**5.1 Queue design**
- Main queue key: `triage:jobs`
- DLQ key: `triage:dlq`
- Job schema:
```python
class QueueJob(BaseModel):
    job_id: str            # uuid4 — idempotency key
    job_type: Literal["replay_test", "retrain", "rollback"]
    model_name: str
    model_version: str
    investigation_id: str
    created_at: datetime
    attempt: int = 0
    max_attempts: int = 3
    payload: dict          # job-type-specific params
```

**5.2 `agent/app/queue/producer.py`**
```python
import redis.asyncio as aioredis
import json
from app.schemas.tool_io import QueueJob

async def enqueue_job(redis_client: aioredis.Redis, job: QueueJob) -> None:
    # Check idempotency: if job_id already in redis set "triage:seen_jobs", skip
    # SADD triage:seen_jobs {job_id}  (with TTL 24h)
    # LPUSH triage:jobs {job.model_dump_json()}
    ...
```

**5.3 `agent/app/queue/worker.py`**
```python
# Standalone process (separate container service in compose)
# BRPOP triage:jobs with timeout
# Parse QueueJob
# Route to handler: replay_test_handler, retrain_handler, rollback_handler
# On success: call back model service (or agent) with result
# On transient failure: re-enqueue with incremented attempt + exponential delay
# On max attempts exceeded: LPUSH triage:dlq {job with error}
# All errors caught specifically — never bare except
# Structured logging for every state transition
```

**5.4 Tool handlers**
```python
# agent/app/tools/replay_test.py
async def replay_test_handler(job: QueueJob) -> dict | ToolError:
    # POST to model_service /drift/compute to trigger fresh computation
    # Pull test set results from MLflow artifacts
    # Return metrics comparison

# agent/app/tools/retrain_model.py  
async def retrain_handler(job: QueueJob) -> dict | ToolError:
    # Trigger training script (subprocess or dedicated training service)
    # Register new model version in MLflow
    # Return new version details

# agent/app/tools/rollback_model.py
async def rollback_handler(job: QueueJob) -> dict | ToolError:
    # Set "staging" alias to previous version in MLflow
    # Does NOT touch "production" alias — that requires promotion gate
    # Returns rollback confirmation
```

**5.5 Commit**
```bash
git commit -m "feat(queue): Redis job queue, idempotency, DLQ, exponential backoff, worker"
```

---

## PHASE 6 — STREAMLIT DASHBOARD (≈2 hours)

### Goal
Single dashboard surfacing all four views with auto-refresh.

### Steps

**6.1 `dashboard/app.py`**
```python
import streamlit as st

st.set_page_config(page_title="Drift Triage Co-Pilot", layout="wide")
st.title("🛡️ Drift Triage Co-Pilot")
# Navigation via st.navigation or sidebar
```

**6.2 `dashboard/pages/registry.py`**
```python
# Polls GET model_service/registry/versions every 30s
# Shows: version, alias (staging/production), model_hash, test_auc, test_f1, registered_at
# Promote button → POST model_service/registry/promote/{version}
# Color code: production = green, staging = yellow
```

**6.3 `dashboard/pages/investigations.py`**
```python
# Polls GET agent/investigations every 10s
# Shows table: investigation_id, severity, started_at, status, model_version
# Click row → show full trajectory (messages exchanged between supervisor and sub-agents)
# Status badges: open (🟡), resolved (🟢), escalated (🔴)
```

**6.4 `dashboard/pages/queue_monitor.py`**
```python
# Polls Redis directly: LLEN triage:jobs, LLEN triage:dlq
# Shows queue depth chart over time (stored in session_state)
# Shows DLQ items: job_id, job_type, error, attempts — with "Retry" and "Dismiss" buttons
```

**6.5 `dashboard/pages/hil_inbox.py`**
```python
# Polls GET agent/investigations?status=awaiting_approval every 5s
# For each pending: show investigation summary, triage assessment, proposed action
# "Approve" button → POST agent/investigations/{id}/approve
# "Reject" button → POST agent/investigations/{id}/reject
# This is the ONLY place Production-touching actions can be approved
```

**6.6 Commit**
```bash
git commit -m "feat(dashboard): registry, investigations, queue monitor, HIL inbox pages"
```

---

## PHASE 7 — INTEGRATION & CONTRACT (≈1 hour)

### Goal
Both services talk to each other correctly. Webhook signature verified. Shared contract documented.

### Steps

**7.1 Document the API contract in `ARCH.md`**
```markdown
## Service Contract v1.0

### Platform → Agent (drift alert)
POST http://agent:8001/webhooks/drift
Header: X-Webhook-Signature: sha256=<hmac>
Header: X-Webhook-Version: 1.0
Body: DriftWebhookPayload (see agent/app/schemas/webhook.py)

### Agent → Platform (promotion request)
POST http://model_service:8000/registry/promote/{version}
Header: X-HIL-Approval-Token: <token from HIL approval>
Body: PromotionRequest (see model_service/app/schemas/registry.py)

Breaking change policy: bump webhook_version field + add migration guide in DECISIONS.md
```

**7.2 HMAC verification in agent**
```python
# agent/app/routes/webhook_receiver.py
import hmac, hashlib
from fastapi import Header, HTTPException, Request

async def verify_webhook_signature(
    request: Request,
    x_webhook_signature: str = Header(...),
) -> None:
    body = await request.body()
    expected = hmac.new(
        settings.webhook_secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(f"sha256={expected}", x_webhook_signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
```

**7.3 Integration smoke test**
```bash
# With docker-compose up running:
# 1. Hit POST model_service:8000/predict with a valid payload
# 2. POST model_service:8000/drift/compute to force a report
# 3. Confirm agent received webhook (check agent logs)
# 4. Confirm investigation appears in dashboard
```

**7.4 Commit**
```bash
git commit -m "feat(integration): webhook HMAC verification, contract documentation"
```

---

## PHASE 8 — TESTS & CI (≈2 hours)

### Goal
Pydantic schema tests, tool logic tests with mocked LLM, snapshot trajectory tests, CI workflow.

### Steps

**8.1 Agent snapshot trajectory tests**

This is the most important test requirement. The pattern:
```python
# agent/tests/fixtures/triage_critical_drift.json
# Store a recorded trajectory: input event → supervisor decisions → sub-agent calls → final state
# On each test run, replay with mocked LLM and assert trajectory matches fixture

# agent/tests/test_supervisor_routing.py

import json
from pathlib import Path
import pytest
from unittest.mock import AsyncMock, patch

FIXTURES = Path(__file__).parent / "fixtures"

@pytest.mark.asyncio
async def test_critical_drift_routes_to_action_agent():
    """Critical severity drift must route through triage then action, never skip."""
    fixture = json.loads((FIXTURES / "triage_critical_drift.json").read_text())

    # Mock the LLM — test runs without API key
    with patch("app.graph.triage_agent.get_llm_client") as mock_llm:
        mock_llm.return_value = AsyncMock(
            invoke=AsyncMock(return_value=fixture["mocked_llm_response"])
        )
        # Run graph with fixture input
        result = await run_graph(fixture["input_event"])

    assert result["triage_result"] is not None
    assert result["action_decision"] is not None
    assert result["action_decision"]["requires_human_approval"] is True

@pytest.mark.asyncio  
async def test_warn_severity_does_not_require_hil():
    """Warn severity should dispatch replay_test without HIL."""
    ...

@pytest.mark.asyncio
async def test_ok_severity_resolves_immediately():
    """OK severity: comms agent wraps up, no queue jobs dispatched."""
    ...
```

**8.2 Pydantic schema tests**
```python
# agent/tests/test_tool_schemas.py
def test_drift_webhook_rejects_unknown_severity():
    with pytest.raises(ValidationError):
        DriftWebhookPayload(severity="catastrophic", ...)  # not in Literal

def test_queue_job_idempotency_key_is_uuid():
    job = QueueJob(job_type="retrain", ...)
    assert len(job.job_id) == 36  # uuid4 format
```

**8.3 Model fidelity replay test**
```python
# training/test_model_fidelity.py
# Load reference test set predictions stored during training
# Re-run predictions on saved test features
# Assert all probabilities match to 1e-12 tolerance (exact reproducibility check)
def test_model_predictions_are_deterministic():
    saved = np.load("training/test_predictions_reference.npy")
    current = pipeline.predict_proba(X_test)[:, 1]
    np.testing.assert_allclose(current, saved, atol=1e-12)
```

**8.4 `.github/workflows/ci.yml`**
```yaml
name: CI
on: [push, pull_request]

jobs:
  test-agent:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install uv
      - run: cd agent && uv sync --frozen
      - run: cd agent && uv run ruff check .
      - run: cd agent && uv run pytest tests/ -q
        env:
          # No real API keys — LLM is mocked in all tests
          ANTHROPIC_API_KEY: "test-key-not-used"
          AGENT_DATABASE_URL: "postgresql+asyncpg://test:test@localhost/test"

  test-model-service:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install uv
      - run: cd model_service && uv sync --frozen
      - run: cd model_service && uv run ruff check .
      - run: cd model_service && uv run pytest tests/ -q

  build-images:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: docker compose build
```

**8.5 Commit**
```bash
git commit -m "test(agent): snapshot trajectory tests, schema tests, fidelity replay, CI workflow"
```

---

## PHASE 9 — DOCKER & FULL STACK VERIFICATION (≈1 hour)

### Goal
`docker-compose up` from clean clone works. All services healthy. Demo flow works end-to-end.

### Steps

**9.1 Finalize all Dockerfiles**

Each Dockerfile pattern (same for all services):
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY app/ ./app/
EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Worker Dockerfile overrides CMD:
```dockerfile
CMD ["uv", "run", "python", "-m", "app.queue.worker"]
```

**9.2 .dockerignore for each service**
```
.git
.gitignore
.env
.env.*
__pycache__/
*.py[cod]
.venv/
tests/
*.md
.coverage
```

**9.3 Add healthchecks to docker-compose**
```yaml
model_service:
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
    interval: 10s
    timeout: 5s
    retries: 5
```

Add `GET /health` to each FastAPI service (returns `{"status": "ok", "model_loaded": bool}`).

**9.4 Alembic entrypoint**
Add a migration step to model_service startup (or a separate init container):
```yaml
  db_migrate:
    build: ./model_service
    command: uv run alembic upgrade head
    env_file: .env
    depends_on: [postgres]
    networks: [triage_net]
    restart: "no"
```

**9.5 Full stack smoke test**
```bash
cp .env.example .env
# Fill in OPENAI/ANTHROPIC keys
docker-compose up --build -d
# Wait for all healthchecks to pass
docker-compose ps
# Run smoke test:
curl -X POST http://localhost:8000/predict -H "Content-Type: application/json" \
  -d '{"age": 35, "job": "management", "marital": "married", ...}'
# Check dashboard at localhost:8501
# Trigger drift: POST localhost:8000/drift/compute
# Watch agent investigate at localhost:8501/investigations
```

**9.6 Commit**
```bash
git commit -m "chore(docker): finalize Dockerfiles, healthchecks, db migration init container"
```

---

## PHASE 10 — DOCUMENTATION & PRESENTATION PREP (≈1 hour)

### Steps

**10.1 `ARCH.md`** — Architecture diagram (ASCII or Mermaid) showing:
- Data flow: predict → store → drift compute → webhook → agent → queue → worker → promote
- Service boundaries and ports
- Network topology
- Persistence: what lives in Postgres, Redis, MLflow, volumes

**10.2 `DECISIONS.md`** — One entry per non-obvious decision:
- Why GradientBoostingClassifier (or whichever you chose)
- Why PSI + chi2 (not just one)
- Why Redis over Postgres queue (speed, atomic LPUSH/BRPOP)
- Why webhook over polling (push is real-time, polling adds latency and wasted calls)
- Why LangGraph for supervisor (native checkpoint/resume, interrupt support)
- Threshold rule: recall >= 0.75 rationale (false negatives cost subscriptions; better to over-predict)
- Why pdays_contacted flag instead of raw pdays

**10.3 `RUNBOOK.md`** — Operational runbook:
- How to start the stack
- How to trigger a manual drift check
- How to approve/reject a HIL request
- How to retry a DLQ job
- How to rollback the model manually
- How to run tests
- Common failure modes and fixes

**10.4 `README.md`** — Submission format requirements:
```markdown
# Drift Triage Co-Pilot

## Team
- [Name 1] | [Name 2]

## Quick Start
cp .env.example .env && docker-compose up

## Architecture
See ARCH.md

## Model
- Registered name: bank_churn_classifier
- Test AUC: [X]  Test F1: [X]
- Operating threshold: [X] (rule: highest threshold where recall >= 0.75)

## LLM
- claude-sonnet-4-20250514 — chosen because structured outputs are robust, low latency for sub-agent calls

## Documentation
- ARCH.md — architecture overview
- DECISIONS.md — engineering decisions log
- RUNBOOK.md — operational guide
```

**10.5 Tag release**
```bash
git tag v0.1.0-week5
git push origin main --tags
```

---

## FRIDAY DEMO SCRIPT (5 minutes)

**Minute 1 — Architecture walkthrough** (point at ARCH.md diagram):
- "Data flows from prediction → stored → rolling window drift check → if severity changes → webhook to agent"
- "Agent is a LangGraph supervisor with 3 sub-agents persisted in Postgres"
- "Slow actions go through Redis queue with idempotency so retries don't double-train"

**Minute 2 — Live drift injection**:
- Open dashboard
- Show current model in registry, no active investigations
- Edit `.env` or use a dedicated drift-injection endpoint to shift `euribor3m` distribution
- POST /drift/compute
- Watch severity change to `critical`, webhook fires, agent opens investigation

**Minute 3 — Agent investigation + HIL**:
- Show investigation appearing in dashboard
- Triage agent assesses: "euribor3m PSI=0.34 — macroeconomic shift"
- Action agent decides: retrain required, HIL approval needed
- Switch to HIL Inbox tab — approval pending
- Click Approve
- Watch queue job dispatched (queue depth goes from 0 to 1 to 0)

**Minute 4 — CI failure demo**:
- Show CI workflow
- Edit a trajectory fixture to have wrong routing decision
- Push — CI fails on snapshot trajectory test
- "This is how we catch regressions in agent logic before they reach production"

**Minute 5 — Bug you fixed**:
- Describe one real bug you hit (LangGraph checkpoint resume, HMAC verification, pdays encoding, etc.)
- Show the commit that fixed it

---

## ENGINEERING STANDARDS CHECKLIST (verify before submission)

```
□ Every route handler is async. No requests, no time.sleep.
□ Every dependency (DB session, model, redis) uses Depends(). No globals in routes.
□ Model + embedder + engine loaded once in lifespan, disposed on shutdown.
□ All config in Settings class. extra="forbid". Zero os.getenv() outside config.py.
□ Pydantic models at every boundary: HTTP bodies, webhook payloads, tool inputs/outputs.
□ Every external call: timeout + tenacity retries (transient only) + ToolError on failure.
□ Tools never raise — they return ToolError. Agent loop never crashes on tool failure.
□ Prompts in .md files, not inline strings.
□ Structured logging (structlog) everywhere. Zero print() statements.
□ No secrets in code or git history. .env in .gitignore from commit zero.
□ Each service has its own Dockerfile. Stack comes up with docker-compose up.
□ Alembic migrations for all schema changes. No create_all() in production.
□ Snapshot trajectory tests pass with mocked LLM (no API key in CI).
□ Fidelity replay test asserts predictions match to 1e-12.
□ CI runs on every push. Failing CI blocks merge.
□ uv used everywhere. uv.lock committed.
□ duration dropped immediately. pdays sentinel handled. unknown kept as valid category.
□ Operating threshold: highest threshold where validation recall >= 0.75.
□ Promotion gate enforces all checklist items before setting production alias.
□ HIL inbox is the only path to Production-touching actions.
□ Redis jobs have idempotency keys. DLQ exists. Max retries enforced.
□ LangGraph checkpoint: kill agent mid-investigation, restart, confirm it resumes not restarts.
□ Webhook HMAC verified on agent side before processing.
□ ARCH.md, DECISIONS.md, RUNBOOK.md all written.
□ Tag v0.1.0-week5 pushed before Thursday midnight.
```

---

## COMMON TRAPS TO AVOID

| Trap | Correct approach |
|------|-----------------|
| `duration` kept in features | Drop it in `load_and_clean()` before anything else |
| `pdays=999` treated as -1 or NaN | Create `pdays_contacted` flag, drop raw column |
| `unknown` imputed or dropped | Leave as string — OHE `handle_unknown="ignore"` handles unseen at inference |
| `requests` library in async routes | Use `httpx.AsyncClient` everywhere |
| Model loaded per-request | Load in `lifespan`, attach to `app.state` |
| LLM output parsed with regex | Use structured outputs → Pydantic model |
| Promotion triggered directly by agent | Must go through promotion gate + HIL approval token |
| Bare `except Exception` | Catch specific exceptions only |
| `print()` for debugging | `structlog.get_logger().info(...)` |
| `os.getenv()` scattered in code | Only in `Settings` class |
| Dockerfile copies `.env` file | Use `env_file:` in docker-compose, never bake secrets into image |
| Two retrain jobs from one event | Idempotency key on queue job prevents duplicates |
| Agent crashes on tool timeout | Tool returns `ToolError(retryable=True)` — agent continues |
```
