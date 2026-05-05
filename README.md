# Drift Triage Co-Pilot

**AIE Bootcamp — Week 5 Project**

## Team
- Partner 1: [Name] — model_service (FastAPI, MLflow, drift engine, promotion gate)
- Partner 2: Ali Hamad — agent (LangGraph, Redis queue, HIL flow, dashboard)

---

## Quick Start

```bash
cp .env.example .env
# Fill in: ANTHROPIC_API_KEY, WEBHOOK_SECRET

docker-compose up --build

# Train and register the model (first time only)
docker-compose run --rm model_service uv run python -m training.train
```

Services:
- Model service: http://localhost:8000/docs
- Agent: http://localhost:8001/docs
- MLflow: http://localhost:5000
- Dashboard: http://localhost:8501

---

## Architecture

See [ARCH.md](ARCH.md) for the full data flow, service map, and network topology.

```
[predictions] → [drift compute] → [webhook] → [LangGraph agent]
                                                      │
                                             triage → action → HIL? → comms
                                                              ↓
                                                       Redis queue → worker
```

---

## Model

- Dataset: UCI Bank Marketing (`bank-additional-full.csv`, ~41k rows)
- Registered name: `bank_churn_classifier`
- Algorithm: GradientBoostingClassifier
- Test AUC: [fill after training]
- Test F1: [fill after training]
- Operating threshold: [fill after training] — rule: highest threshold where recall ≥ 0.75

---

## Agent

- Framework: LangGraph `StateGraph` with `AsyncPostgresSaver` checkpoints
- LLM: `claude-sonnet-4-20250514`
- Sub-agents: triage → action → comms
- HIL: production-touching actions require human approval via dashboard inbox
- Queue: Redis `LPUSH`/`BRPOP` with idempotency keys, exponential backoff, DLQ

---

## Running Tests

```bash
# Agent (LLM fully mocked — no API key needed)
cd agent && uv run pytest tests/ -q

# Model service
cd model_service && uv run pytest tests/ -q
```

---

## Documentation

- [ARCH.md](ARCH.md) — architecture overview, data flow, service contract
- [DECISIONS.md](DECISIONS.md) — engineering decisions log
- [RUNBOOK.md](RUNBOOK.md) — operational guide (start stack, trigger drift, approve HIL, retry DLQ)
