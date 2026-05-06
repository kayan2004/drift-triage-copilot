# CLAUDE.md — Drift Triage Co-Pilot
# This file is read by Claude Code on every session. Keep it accurate.

---

## WHAT THIS PROJECT IS

A self-healing MLOps stack for the AIE Bootcamp Week 5 project.
We train a binary classifier on the UCI Bank Marketing dataset, serve it, watch it for drift,
and run a LangGraph supervisor agent that investigates drift events, dispatches remediation
actions through a Redis queue, and pauses for human approval before touching Production.

Full spec is in `DRIFT_TRIAGE_PLAN.md`.
Architecture diagram is in `ARCH.md`.
Engineering decisions log is in `DECISIONS.md`.
Operational runbook is in `RUNBOOK.md`.

---

## TEAM

- Partner 1: [Name] — owns model_service (FastAPI, MLflow, drift engine, promotion gate)
- Partner 2: [Name] — owns agent (LangGraph, Redis queue, HIL flow, dashboard)

Both partners must be able to explain ALL code on Friday. We will be asked to explain each other's code.

---

## STACK

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| Package manager | uv — always `uv add`, never `pip install` |
| Model service | FastAPI + Uvicorn |
| Agent | LangGraph + FastAPI receiver |
| ML | scikit-learn, MLflow |
| Database | PostgreSQL 16 + SQLAlchemy 2.x async + asyncpg |
| Migrations | Alembic only — never `Base.metadata.create_all` |
| Queue | Redis 7 |
| Dashboard | Streamlit |
| HTTP client | httpx (async) — never `requests` |
| LLM | Anthropic Claude (claude-sonnet-4-20250514) |
| Structured outputs | Pydantic v2 — never regex on LLM output |
| Logging | structlog (JSON) — never print() |
| Linter/formatter | ruff |
| Containers | Docker + docker-compose |
| CI | GitHub Actions |

---

## NON-NEGOTIABLE ENGINEERING RULES
# Claude Code must enforce these on every file it writes or edits.

### Async
- Every route handler, DB call, HTTP call, LLM SDK call must be `async def` and `await`ed.
- Never use `requests`, `time.sleep`, or sync DB sessions anywhere in the request path.
- Use `httpx.AsyncClient` for all outbound HTTP.
- CPU-bound work (model inference if heavy) → `asyncio.to_thread()`.

### Dependency Injection
- Never instantiate DB engines, LLM clients, ML models, or Redis clients inside route handlers.
- Use `FastAPI.Depends()` for all shared resources.
- Heavy singletons (model, engine, redis) live in `lifespan()` attached to `app.state`.
- Per-request resources (DB session) use `yield` in a Depends function.

### Configuration
- One `Settings` class per service using `pydantic-settings` with `extra="forbid"`.
- Zero `os.getenv()` calls outside `config.py`. Zero hardcoded URLs, ports, model names.
- `@lru_cache(maxsize=1)` on `get_settings()`.

### Validation
- Pydantic model at every boundary: HTTP request body, HTTP response, webhook payload,
  tool input, tool output, LLM structured output, queue job.
- Never trust client-side validation.

### Error Handling
- `HTTPException` with correct status codes. Never `200 OK` with an error body.
- Never leak stack traces to clients. Full trace in logs, sanitized message to client.
- Never `except:` or `except Exception` with silent swallowing.
- Catch specific exception types only.
- Never retry non-transient errors (4xx).
- LLM tools must return `ToolError(error=..., retryable=bool)` on failure — never raise.

### Retries
- Use `tenacity` with `stop_after_attempt(3)`, `wait_exponential`, `retry_if_exception_type`.
- Only retry transient errors: `httpx.TimeoutException`, `httpx.NetworkError`, 5xx responses.

### Logging
- `structlog.get_logger()` in every module. Named fields, not f-strings.
- Log: request IDs, user/investigation IDs, tool calls, queue transitions, errors.
- Never log: secrets, API keys, full request bodies with PII.

### Type Hints
- Every function, every argument, every return type. No exceptions. `mypy` strict.

### File Size & Naming
- Never exceed 300 lines per file. Split by concern.
- Name files for what they do: `drift_calculator.py`, not `utils.py`.
- Never put endpoints in `main.py` — use `APIRouter` from day one.

### Security
- `.env` in `.gitignore` from commit zero. Never commit secrets.
- HMAC-SHA256 on all webhooks. Verify on receipt.
- All env var access through `Settings` only.

### Git
- Branches: `feature/`, `bugfix/`, `hotfix/`, `refactor/`, `docs/`, `test/`, `chore/`
- Commits: `feat(scope): imperative summary` (Conventional Commits, under 72 chars)
- PRs: one concern, under 400 lines, squash on merge.

---

## REPOSITORY LAYOUT

```
drift-triage/
├── model_service/              # FastAPI: predictions, drift, registry, webhooks
│   ├── app/
│   │   ├── main.py             # app + lifespan ONLY
│   │   ├── config.py           # Settings
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
│   ├── migrations/
│   ├── tests/
│   ├── pyproject.toml
│   ├── uv.lock
│   └── Dockerfile
│
├── agent/                      # LangGraph supervisor + sub-agents
│   ├── app/
│   │   ├── main.py             # FastAPI: webhook receiver + HIL endpoint
│   │   ├── config.py
│   │   ├── dependencies.py
│   │   ├── graph/
│   │   │   ├── supervisor.py   # StateGraph, checkpointing, interrupt
│   │   │   ├── triage_agent.py
│   │   │   ├── action_agent.py
│   │   │   └── comms_agent.py
│   │   ├── tools/
│   │   │   ├── replay_test.py
│   │   │   ├── retrain_model.py
│   │   │   ├── rollback_model.py
│   │   │   └── fetch_drift_report.py
│   │   ├── prompts/            # Prompts as .md files — never inline strings
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
│
├── dashboard/                  # Streamlit
│   ├── app.py
│   ├── pages/
│   │   ├── registry.py
│   │   ├── investigations.py
│   │   ├── queue_monitor.py
│   │   └── hil_inbox.py
│   ├── pyproject.toml
│   └── Dockerfile
│
├── training/                   # Not in prod image
│   ├── train.py
│   └── reference_stats.json    # Written by train.py, loaded by model_service at startup
│
├── .github/workflows/ci.yml
├── docker-compose.yml
├── .env.example
├── CLAUDE.md                   # This file
├── ARCH.md
├── DECISIONS.md
└── RUNBOOK.md
```

---

## SERVICE MAP

| Service | Port | Responsibility |
|---|---|---|
| `postgres` | 5432 | Predictions, drift reports, model versions, LangGraph checkpoints |
| `redis` | 6379 | Job queue (`triage:jobs`), DLQ (`triage:dlq`), idempotency set |
| `mlflow` | 5000 | Model registry, artifact storage |
| `model_service` | 8000 | Predictions, drift computation, registry, outbound webhooks |
| `agent` | 8001 | Drift webhook receiver, HIL endpoints, investigation API |
| `queue_worker` | — | Consumes Redis queue, runs slow tools |
| `dashboard` | 8501 | Streamlit UI: registry, investigations, queue, HIL inbox |

Services communicate by name over `triage_net`. Never hardcode IPs.

---

## DATASET — CRITICAL FACTS

Dataset: `bank-additional-full.csv` (UCI Bank Marketing, ~41k rows, `;` separator)
Target: `y` → encode as `(df["y"] == "yes").astype(int)`. ~11% positive (imbalanced).
Split: stratified 60/20/20, `random_state=42`.

### Known traps — Claude Code must never get these wrong:
1. **DROP `duration` IMMEDIATELY** after loading. It leaks the target (recorded after call ends).
   Never use it as a feature.
2. **`pdays == 999` is a sentinel** meaning "never contacted before".
   Create `pdays_contacted = (df["pdays"] != 999).astype(int)`, then drop raw `pdays`.
3. **`unknown` is a real category**, not missing data. Never impute, drop, or treat as NaN.
   `OneHotEncoder(handle_unknown="ignore")` handles it correctly.

---

## DRIFT DETECTION — HOW IT WORKS

Reference baseline: `training/reference_stats.json` (written by `train.py`, loaded at startup).

Rolling window: last N predictions from DB (default 500, set via `Settings.drift_window_size`).

Metrics:
- **PSI** (Population Stability Index) on numeric features — 10-bucket comparison.
  PSI < 0.1 → ok | 0.1–0.2 → warn | > 0.2 → critical
- **Chi-squared p-value** on categorical features.
  p > 0.05 → ok | 0.01–0.05 → warn | < 0.01 → critical
- **Output drift**: |current positive rate − reference positive rate|.
  > 0.05 → warn | > 0.10 → critical

Overall severity = max severity across all features + output.

Webhook fires to agent only when severity CHANGES (ok→warn, warn→critical, etc.).

---

## AGENT TOPOLOGY

```
START → supervisor
supervisor → triage_agent       (always first on new event)
triage_agent → supervisor
supervisor → action_agent       (after triage assessment)
action_agent → supervisor
supervisor → INTERRUPT          (if action requires HIL)
[human approves in dashboard]
supervisor → action_agent       (resumes, dispatches to queue)
action_agent → supervisor
supervisor → comms_agent
comms_agent → supervisor
supervisor → END
```

Persistence: `AsyncPostgresSaver` from `langgraph-checkpoint-postgres`.
Thread ID = `drift_event.event_id` (one LangGraph thread per investigation).
Kill and restart agent → must resume from last checkpoint, not start over.

---

## WEBHOOK CONTRACT v1.0

### Platform → Agent (drift alert)
```
POST http://agent:8001/webhooks/drift
Headers:
  Content-Type: application/json
  X-Webhook-Signature: sha256=<hmac-sha256 of body using WEBHOOK_SECRET>
  X-Webhook-Version: 1.0
Body: DriftWebhookPayload (see agent/app/schemas/webhook.py)
```

### Agent → Platform (promotion request)
```
POST http://model_service:8000/registry/promote/{version}
Headers:
  X-HIL-Approval-Token: <token minted at HIL approval time>
Body: PromotionRequest
```

Breaking changes to this contract: bump `webhook_version`, add entry to `DECISIONS.md`.

---

## PROMOTION GATE — ALL MUST PASS

Before setting `production` alias in MLflow, assert:
1. `test_auc >= 0.75`
2. `test_recall >= 0.75` at operating threshold
3. `model_card.json` exists and sha256 hash matches registered binary
4. No active `critical` drift alert in DB
5. Valid `X-HIL-Approval-Token` present (issued by agent HIL flow)

If any check fails: `HTTPException(status_code=422, detail=<specific failure message>)`.

---

## QUEUE JOB SCHEMA

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
    payload: dict
```

Redis keys: `triage:jobs` (main), `triage:dlq` (dead-letter), `triage:seen_jobs` (idempotency set, TTL 24h).

---

## OPERATING THRESHOLD RULE

Tune on validation set: iterate thresholds 0.95 → 0.01 in steps of 0.01.
Pick the **highest** threshold where `recall >= 0.75`.
Store threshold in MLflow model card and in `app.state.model_bundle`.
Apply at inference time: `label = 1 if prob >= threshold else 0`.

---

## TESTING REQUIREMENTS

### Snapshot trajectory tests (agent/tests/)
- Record real agent trajectories as JSON fixtures in `tests/fixtures/`.
- On test run: replay with mocked LLM (no API key needed), assert routing matches fixture.
- Must cover: critical severity routes to HIL, warn severity auto-dispatches, ok resolves immediately.

### Schema tests
- Every Pydantic model: test valid input accepted, test invalid input raises ValidationError.

### Model fidelity replay (training/)
- Save reference predictions as `test_predictions_reference.npy` after training.
- Test: reload model, re-predict, assert `np.allclose(..., atol=1e-12)`.

### CI (GitHub Actions)
- Runs on every push and PR.
- Steps: ruff check → pytest (LLM mocked) → docker compose build.
- Failing CI blocks merge. No exceptions.

---

## COMMON MISTAKES — CLAUDE CODE MUST AVOID THESE

| Wrong | Correct |
|---|---|
| `import requests` | `import httpx` |
| `time.sleep(n)` | `await asyncio.sleep(n)` |
| `os.getenv("X")` in a route | Import `get_settings()` from `config.py` |
| Model loaded inside route handler | Loaded in `lifespan`, injected via `Depends` |
| `except Exception: pass` | Catch specific type, log, re-raise or return `ToolError` |
| `print(f"debug: {x}")` | `log.info("event.name", field=x)` |
| Inline prompt string in agent code | Load from `prompts/<name>.md` file |
| `Base.metadata.create_all()` | `alembic upgrade head` |
| Retry a 400 error | Only retry transient errors (timeout, network, 5xx) |
| Tool raises exception | Tool returns `ToolError(error=..., retryable=bool)` |
| Hardcode `http://localhost:8000` | Use `settings.model_service_url` |
| `duration` in feature list | Drop it immediately in `load_and_clean()` |
| `pdays` raw value as feature | Use `pdays_contacted` flag (1 if pdays != 999) |

---

## HOW TO RUN

```bash
# First time
cp .env.example .env
# Fill in: ANTHROPIC_API_KEY, OPENAI_API_KEY (if used), WEBHOOK_SECRET

# Start everything
docker-compose up --build

# Train and register model (run once, or after reset)
docker-compose run --rm model_service uv run python -m training.train

# Run tests
cd agent && uv run pytest tests/ -q
cd model_service && uv run pytest tests/ -q

# Trigger manual drift check
curl -X POST http://localhost:8000/drift/compute

# View dashboard
open http://localhost:8501

# View MLflow
open http://localhost:5000
```

---

## SUBMISSION CHECKLIST

```
□ docker-compose up works from clean clone after cp .env.example .env
□ Model registered in MLflow with 3 artifacts (binary, schema, model card)
□ Operating threshold logged and stored
□ Drift detection emits webhook on severity change
□ Agent opens investigation, runs triage → action → comms
□ HIL approval required before Production promotion
□ LangGraph resume from checkpoint after restart
□ Redis queue: idempotency, backoff, DLQ visible in dashboard
□ Snapshot trajectory tests pass with mocked LLM in CI
□ Fidelity replay test passes at 1e-12
□ ARCH.md, DECISIONS.md, RUNBOOK.md complete
□ Tag v0.1.0-week5 pushed before Thursday midnight
□ Both partners can explain all code
```
