"""Demo — everything on one page, top to bottom."""
from __future__ import annotations

import os
import sys

import streamlit as st

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import api
import theme as T

T.inject()

# ─────────────────────────────────────────────────────────────────────────────
# State (fetched once per full page load)
# ─────────────────────────────────────────────────────────────────────────────

versions = api.list_versions()
n_pred   = api.prediction_count()
drift    = api.latest_drift_report()
invs     = api.list_investigations()
ms_ok    = api.model_service_healthy()
agent_ok = api.agent_healthy()

model = (
    next((v for v in versions if "production" in v.get("aliases", [])), None)
    or next((v for v in versions if "staging" in v.get("aliases", [])), None)
)
sev      = (drift or {}).get("severity", "ok")
pending  = [i for i in invs if i.get("status") == "awaiting_approval"]
running  = [i for i in invs if i.get("status") == "open"]
resolved = [i for i in invs if i.get("status") == "resolved"]
latest   = invs[0] if invs else None

# ─────────────────────────────────────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────────────────────────────────────

T.hero(
    "🚁 Drift Triage Co-Pilot",
    "End-to-end demo: inject drift → detect → multi-agent investigation → human approval → resolved.",
    [
        ("Model Service", "ok" if ms_ok    else "crit"),
        ("Agent",         "ok" if agent_ok else "crit"),
        (f"Model v{model.get('version')} · AUC {model.get('test_auc',0):.3f}" if model else "No model", "ok" if model else "crit"),
    ],
)

T.stats([
    {
        "label": "Model in registry",
        "value": f"v{model.get('version')}" if model else "—",
        "sub":   f"{', '.join(model.get('aliases',[]))} · threshold {model.get('threshold',0):.2f}" if model else "run training first",
        "tone":  "ok" if model else "crit",
    },
    {
        "label": "Predictions sent",
        "value": str(n_pred),
        "sub":   "in rolling window",
        "tone":  "ok" if n_pred >= 30 else ("warn" if n_pred else ""),
    },
    {
        "label": "Drift severity",
        "value": sev.upper() if drift else "—",
        "sub":   f"output drift {drift.get('output_drift',0):.3f}" if drift else "not computed",
        "tone":  T.SEV_TONE.get(sev, ""),
    },
    {
        "label": "Investigation",
        "value": "WAITING" if pending else ("RUNNING" if running else ("RESOLVED" if resolved else "—")),
        "sub":   f"{len(pending)} pending · {len(resolved)} resolved",
        "tone":  "warn" if pending else ("ok" if resolved else ("live" if running else "")),
    },
])

st.divider()

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Send drifted predictions
# ─────────────────────────────────────────────────────────────────────────────

s1_done = n_pred >= 30
T.phase_open(1, "Send drifted predictions", "done" if s1_done else "active",
             f"{n_pred} in window")

st.caption("Simulates a population shift — elderly retired customers, telephone, December campaign.")

c1, c2 = st.columns([3, 1])
with c1:
    n_send = st.slider("Batch size", 30, 150, 50, key="n_send")
with c2:
    st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    if st.button("📤 Send", type="primary", width="stretch", disabled=not model):
        with st.spinner(f"Sending {n_send} predictions…"):
            ok, msg = api.send_batch("drifted", n_send)
        (st.success if ok else st.error)(msg)
        if ok:
            st.rerun()

T.phase_close()

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Compute drift
# ─────────────────────────────────────────────────────────────────────────────

s2_done = drift is not None and sev != "ok"
T.phase_open(2, "Compute drift", "done" if s2_done else ("active" if s1_done else "idle"),
             sev.upper() if drift else "not run yet")

b1, b2 = st.columns([1, 2])
with b1:
    st.caption("Compares prediction window against training reference using PSI and χ². "
               "Severity change fires a signed webhook to the agent.")
    if st.button("📊 Compute drift", type="primary", width="stretch", disabled=(n_pred == 0)):
        with st.spinner("Running drift detection…"):
            ok, result = api.compute_drift()
        if ok and isinstance(result, dict):
            ns = result.get("severity", "?")
            if ns != "ok":
                st.success(f"Severity: **{ns.upper()}** — webhook fired, agent investigating.")
            else:
                st.info("Severity OK — no webhook fired.")
            st.rerun()
        else:
            st.error(f"Error: {result}")

with b2:
    if drift:
        import pandas as pd
        psi  = drift.get("psi_scores", {}) or {}
        raw  = drift.get("raw_report", {}) or {}
        sevs = raw.get("psi_severities", {})
        if psi:
            rows = [{"Feature": k, "PSI": round(v, 3), "Level": sevs.get(k, "ok").upper()}
                    for k, v in sorted(psi.items(), key=lambda x: -x[1])]
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

T.phase_close()

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Agent timeline (live, auto-refreshes every 3 s)
# ─────────────────────────────────────────────────────────────────────────────

T.phase_open(3, "Multi-agent investigation", "idle", "")  # header only — state updated inside fragment

@st.fragment(run_every=3)
def _timeline() -> None:
    _invs    = api.list_investigations()
    _pending = [i for i in _invs if i.get("status") == "awaiting_approval"]
    _running = [i for i in _invs if i.get("status") == "open"]
    _resolved = [i for i in _invs if i.get("status") == "resolved"]
    _inv     = _invs[0] if _invs else None

    if not _inv:
        st.caption("The agent will appear here automatically once the webhook fires.")
        return

    inv_id = _inv.get("investigation_id", "")
    detail = api.get_investigation(inv_id)
    if not detail:
        st.error("Could not load investigation detail.")
        return

    status  = detail.get("status", "open")
    triage  = (detail.get("triage_summary") or "").strip()
    action  = (detail.get("proposed_action") or "").strip()
    msgs    = detail.get("messages", []) or []
    started = (detail.get("started_at") or "")[:19]
    updated = (detail.get("updated_at") or "")[:19]
    sev_d   = detail.get("severity", "?")

    T.stats([
        {"label": "Status",   "value": T.STATUS_LABEL.get(status, status),
         "sub": f"started {started}",
         "tone": {"open":"warn","awaiting_approval":"warn","resolved":"ok","escalated":"crit","rejected":"crit"}.get(status,"")},
        {"label": "Severity", "value": sev_d.upper(), "sub": "at detection",
         "tone": T.SEV_TONE.get(sev_d,"")},
        {"label": "Action",   "value": action.replace("_"," ").title() if action else "—",
         "sub": "agent's decision", "tone": "warn" if action else ""},
        {"label": "Updated",  "value": updated[11:] if updated else "—",
         "sub": updated[:10] if updated else "", "tone": ""},
    ])

    T.event("📡 Drift webhook received",
            f"Severity <strong>{sev_d.upper()}</strong> · "
            f"model <code>{detail.get('model_name','?')} v{detail.get('model_version','?')}</code> · "
            f"thread <code>{inv_id[:16]}…</code>",
            "ok", started)

    T.event("🔍 Triage Agent",
            triage if triage else "<em>Analysing PSI / χ² scores…</em>",
            "ok" if triage else "active")

    if triage:
        T.event("⚡ Action Agent",
                f"Decision: <code>{action}</code>" if action else "<em>Choosing remediation…</em>",
                "ok" if action else "active")

    if status == "awaiting_approval":
        T.event("⏸ HIL Interrupt — waiting for human",
                "Graph paused. <strong>Retrain / rollback</strong> require your approval "
                "before anything touches production.",
                "active")
    elif status == "resolved" and action not in ("monitor_only", "replay_test", ""):
        T.event("✅ Human approved · job dispatched",
                f"<code>{action}</code> pushed to <code>triage:jobs</code>. Worker executes.",
                "ok")
    elif status == "rejected":
        T.event("❌ Rejected", "No job dispatched.", "crit")

    if status == "resolved":
        T.event("📢 Comms Agent — closed",
                "Investigation complete. LangGraph thread reached END.", "ok", updated)
    elif status == "escalated":
        T.event("🚨 Escalated", "Flagged for manual review.", "crit", updated)

    # Approve / Reject
    if status == "awaiting_approval":
        st.divider()
        with st.container(border=True):
            st.markdown(
                f'<div style="font-size:20px;font-weight:700;color:var(--warn);margin-bottom:8px;">'
                f'⚡ Proposed: {action.replace("_"," ").upper()}</div>'
                f'<div style="font-size:13px;color:var(--muted);">{triage}</div>',
                unsafe_allow_html=True,
            )
            note = st.text_input("Approver note (optional)", key=f"note_{inv_id}",
                                 placeholder="e.g. December campaign shift — approve retrain")
            ac, rc = st.columns(2)
            with ac:
                if st.button("✅ Approve", key=f"app_{inv_id}", type="primary", width="stretch"):
                    with st.spinner("Dispatching…"):
                        ok, msg = api.approve_investigation(inv_id, note, approved=True)
                    (st.success if ok else st.error)(msg)
                    if ok:
                        st.rerun()
            with rc:
                if st.button("❌ Reject", key=f"rej_{inv_id}", width="stretch"):
                    with st.spinner("Rejecting…"):
                        ok, msg = api.approve_investigation(inv_id, note, approved=False)
                    (st.warning if ok else st.error)(msg)
                    if ok:
                        st.rerun()

    if msgs:
        with st.expander(f"Agent messages ({len(msgs)})", expanded=False):
            for m in msgs:
                T.message_bubble(m.get("role") or m.get("type", "ai"), m.get("content", "") or "(empty)")

_timeline()

T.phase_close()

# ─────────────────────────────────────────────────────────────────────────────
# Footer
# ─────────────────────────────────────────────────────────────────────────────

st.divider()
fc1, fc2 = st.columns([1, 1])
with fc1:
    if st.button("🔄 Refresh", width="stretch"):
        st.rerun()
with fc2:
    if st.button("🗑 Reset demo", width="stretch",
                 help="Clears predictions, drift, investigations and queue. Model stays."):
        with st.spinner("Resetting…"):
            ok, msg = api.reset_demo()
        (st.success if ok else st.error)(msg)
        if ok:
            st.rerun()
