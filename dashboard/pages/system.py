"""System — model registry, queue, and service health."""
from __future__ import annotations

import os
import sys

import streamlit as st

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import api
import theme as T

T.inject()

# ── Data ──────────────────────────────────────────────────────────────────────

ms_ok    = api.model_service_healthy()
agent_ok = api.agent_healthy()
versions = api.list_versions()
jobs_n, dlq_n = api.queue_depths()

prod = next((v for v in versions if "production" in v.get("aliases", [])), None)
stag = next((v for v in versions if "staging"    in v.get("aliases", [])), None)

# ── Hero ──────────────────────────────────────────────────────────────────────

T.hero(
    "🛠 System",
    "Model registry, Redis queue, and service health.",
    [
        ("Model Service", "ok" if ms_ok  else "crit"),
        ("Agent",         "ok" if agent_ok else "crit"),
        (f"Queue: {jobs_n} job(s)", "warn" if jobs_n else "ok"),
        (f"DLQ: {dlq_n}",          "crit" if dlq_n  else "ok"),
    ],
)

T.stats([
    {"label": "Production Model",
     "value": f"v{prod.get('version')}" if prod else "—",
     "sub":   f"AUC {prod.get('test_auc', 0):.3f}" if prod else "no production alias",
     "tone":  "ok" if prod else "warn"},
    {"label": "Staging Model",
     "value": f"v{stag.get('version')}" if stag else "—",
     "sub":   f"AUC {stag.get('test_auc', 0):.3f}" if stag else "no staging alias",
     "tone":  "warn" if stag else ""},
    {"label": "Jobs Queue",
     "value": str(jobs_n),
     "sub":   "triage:jobs",
     "tone":  "warn" if jobs_n > 0 else "ok"},
    {"label": "Dead-Letter Queue",
     "value": str(dlq_n),
     "sub":   "triage:dlq",
     "tone":  "crit" if dlq_n else "ok"},
])

tab_reg, tab_q, tab_h = st.tabs(["📦 Model Registry", "📋 Queue & DLQ", "❤ Service Health"])


# ── Registry ──────────────────────────────────────────────────────────────────

with tab_reg:
    if not versions:
        st.warning("No model versions registered. Run training first.")
    else:
        for v in sorted(versions, key=lambda x: int(x.get("version", 0)), reverse=True):
            aliases = v.get("aliases", []) or []
            is_prod = "production" in aliases
            is_stag = "staging"    in aliases
            tone  = "ok" if is_prod else ("warn" if is_stag else "muted")
            label = "PRODUCTION"  if is_prod else ("STAGING" if is_stag else "REGISTERED")

            with st.container(border=True):
                h1, h2 = st.columns([5, 1])
                h1.markdown(f"### v{v.get('version')} — {v.get('model_name', 'bank_churn_classifier')}")
                h2.markdown(T.pill(label, tone), unsafe_allow_html=True)

                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Test AUC",  f"{v.get('test_auc',  0):.3f}" if v.get("test_auc")    is not None else "—")
                m2.metric("Recall",    f"{v.get('test_recall',0):.3f}" if v.get("test_recall") is not None else "—")
                m3.metric("Threshold", f"{v.get('threshold', 0):.3f}" if v.get("threshold")   is not None else "—")
                m4.metric("Hash",      f"{str(v.get('model_hash','—'))[:12]}…")
                st.caption(f"Run ID: `{v.get('run_id','—')}` · Trained: `{v.get('training_date','—')}`")


# ── Queue & DLQ ───────────────────────────────────────────────────────────────

with tab_q:
    qc1, qc2 = st.columns(2)
    qc1.metric("Jobs Queue (`triage:jobs`)", jobs_n)
    qc2.metric("Dead-Letter Queue (`triage:dlq`)", dlq_n)

    st.divider()
    st.markdown(f"#### Dead-Letter Queue · {dlq_n} item(s)")

    items = api.dlq_items()
    if not items:
        st.success("DLQ is empty.")
    else:
        st.caption("Failed jobs after exhausting retries. Retry to re-enqueue or dismiss to drop.")
        for item in items:
            job_id   = item.get("job_id", "unknown")
            job_type = item.get("job_type", "—")
            error    = item.get("dlq_error", "—")
            attempts = item.get("attempt", "—")
            inv_id   = item.get("investigation_id", "—")

            with st.container(border=True):
                tc1, tc2 = st.columns([5, 1])
                tc1.markdown(f"**`{job_id[:20]}…`** · `{job_type}` · attempts: `{attempts}`")
                tc2.markdown(T.pill("FAILED", "crit"), unsafe_allow_html=True)
                st.caption(f"Investigation: `{inv_id}` · "
                           f"Model: `{item.get('model_name','—')} v{item.get('model_version','—')}`")
                st.markdown(f"**Error:** `{error}`")

                bc1, bc2 = st.columns(2)
                with bc1:
                    if st.button("↩ Retry", key=f"r_{job_id}", width="stretch"):
                        if api.dlq_retry(job_id):
                            st.success("Re-enqueued.")
                            st.rerun()
                        else:
                            st.error("Retry failed.")
                with bc2:
                    if st.button("🗑 Dismiss", key=f"d_{job_id}", width="stretch"):
                        if api.dlq_dismiss(job_id):
                            st.success("Dismissed.")
                            st.rerun()
                        else:
                            st.error("Dismiss failed.")


# ── Service Health ────────────────────────────────────────────────────────────

with tab_h:
    st.markdown("#### Service health")
    for name, url, ok in [
        ("Model Service", api.MODEL_SERVICE_URL, ms_ok),
        ("Agent",         api.AGENT_URL,         agent_ok),
    ]:
        with st.container(border=True):
            c1, c2, c3 = st.columns([2, 4, 1])
            c1.markdown(f"**{name}**")
            c2.code(url, language=None)
            c3.markdown(T.pill("UP" if ok else "DOWN", "ok" if ok else "crit"),
                        unsafe_allow_html=True)


# ── Footer ────────────────────────────────────────────────────────────────────

st.divider()
if st.button("🔄 Refresh", width="stretch"):
    st.rerun()
