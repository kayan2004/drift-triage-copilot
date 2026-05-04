import json
import os
import time

import redis
import streamlit as st

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
AGENT_URL = os.environ.get("AGENT_URL", "http://localhost:8001")

_JOBS_KEY = "triage:jobs"
_DLQ_KEY = "triage:dlq"

st.title("📋 Queue Monitor")

REFRESH_INTERVAL = 10


def get_redis_client() -> redis.Redis:
    return redis.from_url(REDIS_URL, decode_responses=True)


def get_queue_depths() -> tuple[int, int]:
    try:
        r = get_redis_client()
        jobs = r.llen(_JOBS_KEY)
        dlq = r.llen(_DLQ_KEY)
        r.close()
        return jobs, dlq
    except redis.RedisError:
        return 0, 0


def get_dlq_items(count: int = 20) -> list[dict]:
    try:
        r = get_redis_client()
        raw_items = r.lrange(_DLQ_KEY, 0, count - 1)
        r.close()
        items = []
        for raw in raw_items:
            try:
                items.append(json.loads(raw))
            except (json.JSONDecodeError, ValueError):
                items.append({"raw": raw})
        return items
    except redis.RedisError:
        return []


def retry_dlq_item(job_id: str) -> bool:
    try:
        r = get_redis_client()
        items = r.lrange(_DLQ_KEY, 0, -1)
        for raw in items:
            try:
                job = json.loads(raw)
                if job.get("job_id") == job_id:
                    job.pop("dlq_error", None)
                    job["attempt"] = 0
                    r.lrem(_DLQ_KEY, 1, raw)
                    r.lpush(_JOBS_KEY, json.dumps(job))
                    r.close()
                    return True
            except (json.JSONDecodeError, ValueError):
                continue
        r.close()
        return False
    except redis.RedisError:
        return False


def dismiss_dlq_item(job_id: str) -> bool:
    try:
        r = get_redis_client()
        items = r.lrange(_DLQ_KEY, 0, -1)
        for raw in items:
            try:
                job = json.loads(raw)
                if job.get("job_id") == job_id:
                    r.lrem(_DLQ_KEY, 1, raw)
                    r.close()
                    return True
            except (json.JSONDecodeError, ValueError):
                continue
        r.close()
        return False
    except redis.RedisError:
        return False


# Auto-refresh tracking
if "queue_history" not in st.session_state:
    st.session_state.queue_history = []
if "queue_last_refresh" not in st.session_state:
    st.session_state.queue_last_refresh = 0

if st.button("🔄 Refresh"):
    st.session_state.queue_last_refresh = 0

jobs_depth, dlq_depth = get_queue_depths()

# Append to history for sparkline
now = time.time()
st.session_state.queue_history.append({"t": now, "jobs": jobs_depth, "dlq": dlq_depth})
# Keep last 60 data points
st.session_state.queue_history = st.session_state.queue_history[-60:]

# Metrics row
col1, col2 = st.columns(2)
col1.metric("Jobs Queue (triage:jobs)", jobs_depth)
col2.metric("Dead-Letter Queue (triage:dlq)", dlq_depth, delta_color="inverse")

# Depth chart
if len(st.session_state.queue_history) > 1:
    import pandas as pd

    df = pd.DataFrame(st.session_state.queue_history)
    df["time"] = pd.to_datetime(df["t"], unit="s")
    df = df.set_index("time")[["jobs", "dlq"]]
    st.line_chart(df, color=["#1f77b4", "#d62728"])

st.divider()
st.subheader(f"Dead-Letter Queue ({dlq_depth} items)")

dlq_items = get_dlq_items()
if not dlq_items:
    st.info("DLQ is empty.")
else:
    for item in dlq_items:
        job_id = item.get("job_id", "unknown")
        job_type = item.get("job_type", "—")
        error = item.get("dlq_error", "—")
        attempts = item.get("attempt", "—")
        inv_id = item.get("investigation_id", "—")

        with st.expander(f"`{job_id[:16]}…` — {job_type} | attempts: {attempts}"):
            st.markdown(f"**Investigation:** `{inv_id}`")
            st.markdown(f"**Error:** {error}")
            model_str = f"`{item.get('model_name', '—')} v{item.get('model_version', '—')}`"
            st.markdown(f"**Model:** {model_str}")

            c1, c2 = st.columns(2)
            with c1:
                if st.button("↩️ Retry", key=f"retry_{job_id}"):
                    if retry_dlq_item(job_id):
                        st.success("Re-enqueued.")
                        st.rerun()
                    else:
                        st.error("Retry failed.")
            with c2:
                if st.button("🗑️ Dismiss", key=f"dismiss_{job_id}"):
                    if dismiss_dlq_item(job_id):
                        st.success("Dismissed.")
                        st.rerun()
                    else:
                        st.error("Dismiss failed.")

st.session_state.queue_last_refresh = now
st.caption(f"Auto-refreshes every {REFRESH_INTERVAL}s")
time.sleep(REFRESH_INTERVAL)
st.rerun()
