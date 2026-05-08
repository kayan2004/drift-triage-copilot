"""Investigation — vertical timeline of one investigation's lifecycle."""
from __future__ import annotations

import os
import sys

import streamlit as st

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import api
import theme as T

T.inject()

# ── Selector ──────────────────────────────────────────────────────────────────

invs = api.list_investigations()

if not invs:
    T.hero(
        "🔬 Investigation Timeline",
        "No investigations yet. Go to the **Demo** page, send drifted predictions, "
        "and compute drift to start one.",
        [],
    )
    if st.button("🔄 Refresh"):
        st.rerun()
    st.stop()

T.hero(
    "🔬 Investigation Timeline",
    "Step-by-step view of the multi-agent lifecycle — what each agent decided, "
    "what the human approved, and what job was dispatched.",
    [(f"{len(invs)} investigation(s)", "brand")],
)

default_idx = 0
preselect = st.session_state.pop("selected_investigation", None)
if preselect:
    for i, inv in enumerate(invs):
        if inv.get("investigation_id") == preselect:
            default_idx = i
            break

options = {
    f"{T.STATUS_LABEL.get(i.get('status',''), i.get('status','')):<22} "
    f"{(i.get('severity') or '').upper():<10} "
    f"v{i.get('model_version','?'):<4} "
    f"{(i.get('investigation_id') or '')[:12]}…": i.get("investigation_id")
    for i in invs
}

selected_label = st.selectbox("Select investigation", list(options.keys()), index=default_idx)
inv_id = options[selected_label]


# ── Live fragment ─────────────────────────────────────────────────────────────

@st.fragment(run_every=3)
def render(inv_id: str) -> None:
    detail = api.get_investigation(inv_id)
    if not detail:
        st.error("Could not load investigation.")
        return

    status   = detail.get("status", "open")
    severity = detail.get("severity", "?")
    triage   = (detail.get("triage_summary") or "").strip()
    action   = (detail.get("proposed_action") or "").strip()
    messages = detail.get("messages", []) or []
    started  = (detail.get("started_at") or "")[:19]
    updated  = (detail.get("updated_at") or "")[:19]
    model_v  = detail.get("model_version", "?")
    model_n  = detail.get("model_name", "?")

    # ── Stat strip ────────────────────────────────────────────────────────────
    T.stats([
        {"label": "Status",   "value": T.STATUS_LABEL.get(status, status),
         "sub": f"started {started}",
         "tone": {"open": "warn", "awaiting_approval": "warn",
                  "resolved": "ok", "escalated": "crit", "rejected": "crit"}.get(status, "")},
        {"label": "Severity", "value": severity.upper(),
         "sub": "drift level at detection time",
         "tone": T.SEV_TONE.get(severity, "")},
        {"label": "Model",    "value": f"v{model_v}",
         "sub": model_n, "tone": ""},
        {"label": "Action",   "value": action.replace("_", " ").title() if action else "—",
         "sub": "proposed remediation", "tone": "warn" if action else ""},
    ])

    # ── Timeline ──────────────────────────────────────────────────────────────
    st.markdown("### Agent timeline")

    is_done     = status in ("resolved", "rejected", "escalated")
    is_waiting  = status == "awaiting_approval"
    is_running  = status == "open"

    # Step 1 — Drift received
    T.event(
        title="📡 Drift event received",
        body=(f"Webhook from <code>model_service</code> · severity <strong>{severity.upper()}</strong> · "
              f"model <code>{model_n} v{model_v}</code><br>"
              f"LangGraph thread opened · thread_id = <code>{inv_id[:20]}…</code>"),
        tone="ok",
        time_str=started,
    )

    # Step 2 — Triage
    T.event(
        title="🔍 Triage Agent",
        body=(triage if triage else "<em>Analysing PSI / χ² scores…</em>"),
        tone="ok" if triage else ("active" if is_running else "brand"),
        time_str="",
    )

    # Step 3 — Action
    if triage or not is_running:
        T.event(
            title="⚡ Action Agent",
            body=(f"Decision: <code>{action}</code>" if action else "<em>Deciding remediation strategy…</em>"),
            tone="ok" if action else ("active" if is_running else "brand"),
            time_str="",
        )

    # Step 4 — HIL
    if is_waiting:
        T.event(
            title="⏸ HIL Interrupt — awaiting human approval",
            body=("Graph paused. <strong>Retrain</strong> / <strong>rollback</strong> require explicit "
                  "approval before any production change. Approve or reject below."),
            tone="active",
            time_str="",
        )
    elif status == "resolved" and action not in ("monitor_only", "replay_test", ""):
        T.event(
            title="✅ Human approved · job dispatched",
            body=f"HIL token issued · <code>{action}</code> job pushed to <code>triage:jobs</code>",
            tone="ok",
            time_str="",
        )
    elif status == "rejected":
        T.event(
            title="❌ Human rejected",
            body="Investigation closed without dispatching a job.",
            tone="crit",
            time_str="",
        )

    # Step 5 — Comms / done
    if status == "resolved":
        T.event(
            title="📢 Comms Agent — investigation closed",
            body="Outcome summarised. LangGraph thread reached END.",
            tone="ok",
            time_str=updated,
        )
    elif status == "escalated":
        T.event(
            title="🚨 Escalated",
            body="Investigation escalated for manual review.",
            tone="crit",
            time_str=updated,
        )

    # ── Inline approval ───────────────────────────────────────────────────────
    if is_waiting:
        st.divider()
        st.markdown("### Approve or reject")
        with st.container(border=True):
            note = st.text_input("Approver note (optional)", key=f"note_{inv_id}",
                                 placeholder="e.g. December campaign shift confirmed — approve retrain")
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

    # ── Message trajectory ────────────────────────────────────────────────────
    if messages:
        st.divider()
        st.markdown("### Agent messages")
        for msg in messages:
            T.message_bubble(msg.get("role") or msg.get("type", "ai"), msg.get("content", "") or "(empty)")


render(inv_id)

st.divider()
if st.button("🔄 Refresh", width="stretch"):
    st.rerun()
