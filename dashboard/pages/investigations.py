import os
import time

import httpx
import streamlit as st

AGENT_URL = os.environ.get("AGENT_URL", "http://localhost:8001")

st.title("🔍 Investigations")

STATUS_ICON = {
    "open": "🟡",
    "awaiting_approval": "🟠",
    "resolved": "🟢",
    "escalated": "🔴",
    "rejected": "⚫",
}

REFRESH_INTERVAL = 10  # seconds


def fetch_investigations(status: str | None = None) -> list[dict]:
    try:
        params = {"status": status} if status else {}
        r = httpx.get(f"{AGENT_URL}/investigations/", params=params, timeout=5.0)
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


# Auto-refresh
if "inv_last_refresh" not in st.session_state:
    st.session_state.inv_last_refresh = 0

col_filter, col_refresh = st.columns([3, 1])
with col_filter:
    status_filter = st.selectbox(
        "Filter by status",
        ["all", "open", "awaiting_approval", "resolved", "escalated", "rejected"],
    )
with col_refresh:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🔄 Refresh"):
        st.session_state.inv_last_refresh = 0

now = time.time()
if now - st.session_state.inv_last_refresh > REFRESH_INTERVAL:
    st.session_state.inv_last_refresh = now

investigations = fetch_investigations(None if status_filter == "all" else status_filter)

if not investigations:
    st.info("No investigations found.")
else:
    selected_id = st.session_state.get("selected_investigation")

    for inv in investigations:
        inv_id = inv.get("investigation_id", "")
        status = inv.get("status", "open")
        icon = STATUS_ICON.get(status, "⚪")
        severity = inv.get("severity", "—")
        model_ver = inv.get("model_version", "—")
        started = inv.get("started_at", "—")

        col1, col2 = st.columns([5, 1])
        with col1:
            st.markdown(
                f"{icon} **{inv_id[:16]}…** | severity: `{severity}` | "
                f"model: `v{model_ver}` | started: {started}"
            )
        with col2:
            if st.button("Details", key=f"detail_{inv_id}"):
                st.session_state.selected_investigation = inv_id

    if selected_id:
        st.divider()
        st.subheader(f"Investigation: {selected_id[:16]}…")
        detail = fetch_detail(selected_id)
        if detail is None:
            st.error("Could not load investigation detail.")
        else:
            status_icon = STATUS_ICON.get(detail.get("status", ""), "")
            st.markdown(f"**Status:** {status_icon} `{detail.get('status')}`")
            st.markdown(f"**Severity:** `{detail.get('severity', '—')}`")
            model_str = f"`{detail.get('model_name', '—')} v{detail.get('model_version', '—')}`"
            st.markdown(f"**Model:** {model_str}")

            messages = detail.get("messages", [])
            if messages:
                st.markdown("**Trajectory:**")
                for msg in messages:
                    role = msg.get("role", "unknown")
                    content = msg.get("content", "")
                    with st.expander(f"`{role}`"):
                        st.text(content)
            else:
                st.info("No trajectory messages yet.")

        if st.button("Close", key="close_detail"):
            del st.session_state.selected_investigation

last_refresh = int(st.session_state.inv_last_refresh)
st.caption(f"Auto-refreshes every {REFRESH_INTERVAL}s — last refresh: {last_refresh}")
if time.time() - st.session_state.inv_last_refresh > REFRESH_INTERVAL:
    st.rerun()
