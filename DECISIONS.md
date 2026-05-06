# DECISIONS.md — Engineering Decisions Log

Each entry: what we decided, why, and what we considered but rejected.

---

## D-001 — LangGraph for supervisor orchestration

**Decision:** Use LangGraph `StateGraph` with `AsyncPostgresSaver` for the supervisor agent.

**Why:** LangGraph has native interrupt/resume support (`interrupt()` + `aupdate_state()`), which is the cleanest way to implement the Human-in-the-Loop pause without polling. Postgres checkpointing means the agent survives crashes and restarts — the investigation resumes from the exact node it was interrupted at, not from the beginning.

**Alternatives considered:** Plain asyncio task queue (no checkpoint resume), Celery (too heavy, no native graph state), custom FSM (would reimpliment what LangGraph provides).

---

## D-002 — Redis over Postgres for the job queue

**Decision:** Use Redis `LPUSH`/`BRPOP` for the slow-tool job queue.

**Why:** Atomic LPUSH/BRPOP gives exactly-once delivery semantics without advisory locks. Sub-millisecond enqueue latency. DLQ is a second Redis list — trivial to implement. Idempotency set (`SADD triage:seen_jobs`) with TTL 24h prevents duplicate jobs from retries.

**Alternatives considered:** Postgres `SKIP LOCKED` queue — works but adds write load to the same DB that stores checkpoints. Celery/RQ — adds broker complexity; overkill for three job types.

---

## D-003 — PSI + chi2 drift detection (not a single metric)

**Decision:** Use PSI for numeric features and chi2 p-value for categorical features, separately.

**Why:** PSI and chi2 measure different things. PSI quantifies the *magnitude* of distribution shift in numeric features (buckets); chi2 tests whether categorical distributions are statistically independent of the reference. Using both gives coverage across feature types with well-established severity thresholds (PSI 0.1/0.2, chi2 p=0.05/0.01).

**Alternatives considered:** KS test for numerics — valid but PSI is more interpretable for ops teams. Jensen-Shannon divergence — symmetric and bounded but less standard in MLOps tooling.

---

## D-004 — Webhook push over polling for drift alerts

**Decision:** Model service emits a webhook to agent on severity change; agent does not poll.

**Why:** Push is real-time — agent starts investigating immediately after severity changes. Polling adds latency proportional to poll interval and burns DB reads every cycle. Webhook only fires on *change* (ok→warn, warn→critical), not on every compute cycle, so the agent isn't flooded.

**Alternatives considered:** Agent polling `GET /drift/report` every 30s — simpler but lagging and wasteful. SSE/WebSocket — correct but overengineered for a single consumer.

---

## D-005 — HMAC-SHA256 webhook signature verification

**Decision:** Sign all webhooks with HMAC-SHA256 using `WEBHOOK_SECRET`. Agent verifies before processing.

**Why:** Without signature verification, any process that can reach `agent:8001` can inject fake drift events and trigger model retraining or rollback. HMAC-SHA256 is the industry standard (used by GitHub, Stripe, etc.) — simple, stateless, no PKI required.

**Implementation:** `X-Webhook-Signature: sha256=<hex>` header. Agent uses `hmac.compare_digest` (constant-time) to prevent timing attacks.

---

## D-006 — Recall >= 0.75 as operating threshold rule

**Decision:** Tune threshold on validation set: pick the *highest* threshold where recall >= 0.75.

**Why:** The bank marketing dataset is imbalanced (~11% positive). False negatives (missing a subscriber) cost the bank a lost sale. Recall >= 0.75 ensures we catch at least 75% of actual subscribers. We pick the *highest* threshold satisfying this constraint to maximize precision (fewer false positives wasting call-centre time).

**Note:** This threshold is stored in `model_card.json` and `app.state.model_bundle` — applied at inference time, not hardcoded.

---

## D-007 — Drop `duration` immediately on load

**Decision:** Drop `duration` as the first operation in `load_and_clean()`, before any other transformation.

**Why:** `duration` is the last call duration in seconds — it is only known *after* the call ends. Using it as a feature creates target leakage: the model would essentially be predicting from the outcome. This is documented in the UCI dataset description as a known trap.

---

## D-008 — `pdays_contacted` flag instead of raw `pdays`

**Decision:** Replace raw `pdays` with a binary flag `pdays_contacted = (pdays != 999).astype(int)`.

**Why:** `pdays == 999` is a sentinel meaning "never contacted before" — it is not a real number of days. Treating it as a numeric value would give the model a spurious signal (999 days >> any real value). The binary flag captures the meaningful information: was this person contacted in a previous campaign?

---

## D-009 — `unknown` kept as a real category

**Decision:** Never impute or drop `unknown` values in categorical features.

**Why:** In the UCI Bank Marketing dataset, `unknown` is a valid response — the contact simply did not provide that information. Imputing it (e.g., most-frequent) introduces false signal. `OneHotEncoder(handle_unknown="ignore")` handles `unknown` correctly at both train and inference time.

---

## D-010 — Prompts as `.md` files, never inline strings

**Decision:** All LLM prompts live in `agent/app/prompts/*.md`, loaded at module import time.

**Why:** Inline prompt strings scatter across Python files, making them hard to review, diff, and iterate on. `.md` files are visible in the repo, diffable in PRs, and can be reviewed independently of code changes. Prompt changes get their own commits.

---

## D-011 — HIL inbox as the only path to Production

**Decision:** Production-touching actions (retrain, rollback) always set `requires_human_approval=True` in `ActionDecision`. The queue job is only dispatched after a human approves in the HIL inbox.

**Why:** Automated model promotion to Production without human review is a deployment risk. A drift event could be caused by a data pipeline bug, not a genuine distribution shift — in which case retraining on corrupted data would make the model worse. The HIL gate ensures a human sees the triage assessment and proposed action before any irreversible change.

---

## D-012 — One LangGraph thread per investigation

**Decision:** `thread_id = drift_event.event_id` (uuid4 from the webhook payload).

**Why:** Each drift event is a unique investigation. Using `event_id` as thread ID means the checkpointer naturally deduplicates — if the same event arrives twice (network retry), the second run resumes the existing thread rather than starting a new investigation. Idempotent by design.

---

## Webhook Version History

| Version | Date | Changes |
|---|---|---|
| 1.0 | 2026-05-01 | Initial contract |
