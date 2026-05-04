import os
import time

import httpx
import streamlit as st

AGENT_URL = os.environ.get("AGENT_URL", "http://localhost:8001")

st.title("✅ HIL Inbox — Pending Approvals")
st.caption("This is the ONLY place Production-touching actions can be approved.")

REFRESH_INTERVAL = 5


def fetch_pending() -> list[dict]:
    try:
        r = httpx.get(
            f"{AGENT_URL}/investigations/",
            params={"status": "awaiting_approval"},
            timeout=5.0,
        )
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, httpx.ConnectError):
        return []


def fetch_detail(investigation_id: str) -> dict | None:
    try:
        r = httpx.get(f"{AGENT_URL}/investigations/{investigation_id}", timeout=5.0)
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, httpx.ConnectError):
        return None


def approve(investigation_id: str, note: str) -> tuple[bool, str]:
    try:
        r = httpx.post(
            f"{AGENT_URL}/investigations/{investigation_id}/approve",
            json={"approved": True, "approver_note": note},
            timeout=30.0,
        )
        if r.status_code == 200:
            return True, "Approved — action dispatched to queue."
        return False, r.json().get("detail", "Approval failed.")
    except (httpx.HTTPError, httpx.ConnectError) as exc:
        return False, str(exc)


def reject(investigation_id: str, note: str) -> tuple[bool, str]:
    try:
        r = httpx.post(
            f"{AGENT_URL}/investigations/{investigation_id}/approve",
            json={"approved": False, "approver_note": note},
            timeout=10.0,
        )
        if r.status_code == 200:
            return True, "Rejected."
        return False, r.json().get("detail", "Rejection failed.")
    except (httpx.HTTPError, httpx.ConnectError) as exc:
        return False, str(exc)


if "hil_last_refresh" not in st.session_state:
    st.session_state.hil_last_refresh = 0

col1, col2 = st.columns([4, 1])
with col2:
    if st.button("🔄 Refresh"):
        st.session_state.hil_last_refresh = 0

pending = fetch_pending()

if not pending:
    st.success("No pending approvals.")
else:
    st.warning(f"**{len(pending)} action(s) awaiting your approval.**")

    for inv in pending:
        inv_id = inv.get("investigation_id", "")
        severity = inv.get("severity", "—")
        model_ver = inv.get("model_version", "—")
        model_name = inv.get("model_name", "—")

        detail = fetch_detail(inv_id)

        with st.container(border=True):
            st.markdown(f"### 🟠 Investigation `{inv_id[:20]}…`")
            st.markdown(f"**Severity:** `{severity}` | **Model:** `{model_name} v{model_ver}`")

            if detail:
                # Show triage summary from messages
                messages = detail.get("messages", [])
                triage_msg = next((m for m in messages if m.get("role") == "triage_agent"), None)
                action_msg = next((m for m in messages if m.get("role") == "action_agent"), None)

                if triage_msg:
                    with st.expander("Triage Assessment"):
                        st.text(triage_msg.get("content", "—"))
                if action_msg:
                    with st.expander("Proposed Action", expanded=True):
                        st.text(action_msg.get("content", "—"))

            note = st.text_input(
                "Approver note (optional)",
                key=f"note_{inv_id}",
                placeholder="e.g. Reviewed drift report, approved retrain",
            )

            col_approve, col_reject = st.columns(2)
            with col_approve:
                if st.button("✅ Approve", key=f"approve_{inv_id}", type="primary"):
                    ok, msg = approve(inv_id, note)
                    if ok:
                        st.success(msg)
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(msg)
            with col_reject:
                if st.button("❌ Reject", key=f"reject_{inv_id}"):
                    ok, msg = reject(inv_id, note)
                    if ok:
                        st.warning(msg)
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(msg)

st.session_state.hil_last_refresh = time.time()
st.caption(f"Auto-refreshes every {REFRESH_INTERVAL}s")
time.sleep(REFRESH_INTERVAL)
st.rerun()
