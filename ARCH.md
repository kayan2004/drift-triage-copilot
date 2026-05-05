# ARCH.md — Drift Triage Co-Pilot Architecture

## Service Map

| Service | Port | Responsibility |
|---|---|---|
| `postgres` | 5432 | Predictions, drift reports, model versions, LangGraph checkpoints, investigations |
| `redis` | 6379 | Job queue (`triage:jobs`), DLQ (`triage:dlq`), idempotency set (`triage:seen_jobs`) |
| `mlflow` | 5000 | Model registry, artifact storage (model.pkl, schema.json, model_card.json) |
| `model_service` | 8000 | Predictions, drift computation, registry, outbound webhooks |
| `agent` | 8001 | Drift webhook receiver, LangGraph supervisor, HIL endpoints, investigation API |
| `queue_worker` | — | Consumes Redis queue, executes slow tools (retrain, rollback, replay_test) |
| `dashboard` | 8501 | Streamlit UI: model registry, investigations, queue monitor, HIL inbox |

All services communicate over `triage_net`. Never use hardcoded IPs or `localhost`.

---

## Data Flow

```
[Client]
   │
   ▼
POST /predict                     model_service:8000
   │  store prediction → Postgres
   │
   ▼ (background, every N minutes or manual trigger)
POST /drift/compute               model_service:8000
   │  pull last 500 predictions from Postgres
   │  compare against reference_stats.json (loaded at startup from training/)
   │  compute PSI (numeric) + chi2 (categorical) + output drift
   │  classify severity: ok | warn | critical
   │  store DriftReport → Postgres
   │  if severity changed →
   ▼
POST /webhooks/drift              agent:8001
   │  HMAC-SHA256 verified (X-Webhook-Signature)
   │  version checked (X-Webhook-Version: 1.0)
   │  create Investigation record → Postgres
   │  launch background _run_investigation()
   │  return 202 Accepted
   │
   ▼ (LangGraph StateGraph, thread_id = event_id)
supervisor → triage_agent
   │  fetch full drift report from model_service
   │  call Claude → TriageAssessment (JSON, Pydantic-validated)
   │
supervisor → action_agent
   │  call Claude → ActionDecision (JSON, Pydantic-validated)
   │  if action ∈ {retrain, rollback}: requires_human_approval = True
   │
   ├─► if requires_human_approval:
   │       INTERRUPT (LangGraph checkpoint saved to Postgres)
   │       update investigation status → "awaiting_approval"
   │       store hil_token
   │
   │   [Human reviews in dashboard HIL Inbox]
   │   POST /investigations/{id}/approve    agent:8001
   │       graph.aupdate_state(hil_approved=True)
   │       graph resumes from Postgres checkpoint
   │
   └─► action_agent enqueues QueueJob → Redis (triage:jobs)
           job_id = idempotency key (uuid4, TTL 24h in triage:seen_jobs)
   │
   ▼
queue_worker (BRPOP triage:jobs)
   │  route to handler: replay_test | retrain | rollback
   │  on transient failure: re-enqueue with incremented attempt + exponential backoff
   │  on max_attempts exceeded: LPUSH triage:dlq
   │
supervisor → comms_agent
   │  call Claude → CommsReport (JSON, Pydantic-validated)
   │  update investigation status → "resolved" | "escalated"
   │
   ▼ END
```

---

## Persistence

| Data | Store | Key/Table |
|---|---|---|
| Predictions | Postgres | `predictions` |
| Drift reports | Postgres | `drift_reports` |
| Model versions | Postgres + MLflow | `model_versions` + MLflow registry |
| LangGraph checkpoints | Postgres | LangGraph internal tables |
| Investigations | Postgres | `investigations` |
| Queue jobs | Redis | `triage:jobs` (list) |
| Dead-letter jobs | Redis | `triage:dlq` (list) |
| Idempotency keys | Redis | `triage:seen_jobs` (set, TTL 24h) |
| Model artifacts | MLflow volumes | `model.pkl`, `schema.json`, `model_card.json` |
| Reference stats | File (startup) | `training/reference_stats.json` |

---

## LangGraph Agent Topology

```
START
  │
  ▼
supervisor ──────────────────────────────────────────────────────┐
  │                                                               │
  ▼ (no triage_result yet)                                        │
triage_agent → supervisor                                         │
                  │                                               │
                  ▼ (triage done, no action_decision yet)         │
               action_agent → supervisor                          │
                                  │                               │
                  ┌───────────────┴───────────────┐              │
                  ▼                               ▼               │
           requires HIL?                    no HIL needed         │
           await_hil                        comms_agent ──────────┘
           [INTERRUPT]                          │
           [human approves]                     ▼
           action_agent (resume)              END
           comms_agent
               │
               ▼
             END
```

Persistence: `AsyncPostgresSaver`. Thread ID = `drift_event.event_id`.
Kill and restart agent → resumes from last checkpoint.

---

## Service Contract v1.0

### Platform → Agent (drift alert)
```
POST http://agent:8001/webhooks/drift
Headers:
  Content-Type: application/json
  X-Webhook-Signature: sha256=<hmac-sha256 of body using WEBHOOK_SECRET>
  X-Webhook-Version: 1.0
Body: DriftWebhookPayload (see agent/app/schemas/webhook.py)
Response: 202 Accepted
```

### Agent → Platform (promotion request)
```
POST http://model_service:8000/registry/promote/{version}
Headers:
  Content-Type: application/json
  X-HIL-Approval-Token: <token minted at HIL approval time>
Body: PromotionRequest (see model_service/app/schemas/registry.py)
Response: 200 OK | 422 Unprocessable (promotion gate failure)
```

**Breaking change policy**: bump `webhook_version` field in payload, add migration guide in `DECISIONS.md`.

---

## Promotion Gate

Before setting `production` alias in MLflow, ALL must pass:

1. `test_auc >= 0.75`
2. `test_recall >= 0.75` at operating threshold
3. `model_card.json` exists and sha256 hash matches registered binary
4. No active `critical` drift alert in DB
5. Valid `X-HIL-Approval-Token` present (issued by agent HIL flow)

Any failure → `HTTP 422` with specific failure message.

---

## Network Topology

```
                        triage_net (Docker bridge)
┌──────────┐  :5432  ┌──────────────────────────────────────────┐
│ postgres │◄────────┤ model_service | agent | queue_worker      │
└──────────┘         └──────────────────────────────────────────┘
┌──────────┐  :6379         ▲            ▲           ▲
│  redis   │◄───────────────┘            │           │
└──────────┘                             │           │
┌──────────┐  :5000                      │           │
│  mlflow  │◄────────────────────────────┘           │
└──────────┘                                         │
┌───────────┐  :8501                                 │
│ dashboard │◄───────────────────────────────────────┘
└───────────┘  (reads agent:8001 + model_service:8000)
```
