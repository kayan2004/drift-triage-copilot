import os

import httpx
import streamlit as st

MODEL_SERVICE_URL = os.environ.get("MODEL_SERVICE_URL", "http://localhost:8000")

st.title("📦 Model Registry")

ALIAS_COLOR = {"production": "🟢", "staging": "🟡", "none": "⚪"}


@st.cache_data(ttl=30)
def fetch_versions() -> list[dict]:
    try:
        r = httpx.get(f"{MODEL_SERVICE_URL}/registry/versions", timeout=5.0)
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, httpx.ConnectError):
        return []


def promote_version(version: str) -> tuple[bool, str]:
    try:
        r = httpx.post(f"{MODEL_SERVICE_URL}/registry/promote/{version}", timeout=10.0)
        if r.status_code == 200:
            return True, "Promoted successfully."
        return False, r.json().get("detail", "Promotion failed.")
    except (httpx.HTTPError, httpx.ConnectError) as exc:
        return False, str(exc)


if st.button("🔄 Refresh", key="registry_refresh"):
    st.cache_data.clear()

versions = fetch_versions()

if not versions:
    st.warning("No model versions found — model_service may be unavailable.")
else:
    for v in versions:
        alias = v.get("alias", "none")
        icon = ALIAS_COLOR.get(alias, "⚪")
        expanded = alias == "production"
        with st.expander(f"{icon} v{v.get('version')} — {alias.upper()}", expanded=expanded):
            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f"**Model name:** {v.get('name', '—')}")
                st.markdown(f"**Version:** {v.get('version', '—')}")
                st.markdown(f"**Alias:** `{alias}`")
                st.markdown(f"**Registered:** {v.get('registered_at', '—')}")
            with col2:
                st.markdown(f"**Test AUC:** {v.get('test_auc', '—')}")
                st.markdown(f"**Test F1:** {v.get('test_f1', '—')}")
                st.markdown(f"**Threshold:** {v.get('threshold', '—')}")
                st.markdown(f"**Hash:** `{str(v.get('model_hash', '—'))[:16]}…`")

            if alias == "staging":
                ver = v.get("version")
                if st.button(f"Promote v{ver} to Production", key=f"promote_{ver}"):
                    ok, msg = promote_version(str(v.get("version")))
                    if ok:
                        st.success(msg)
                        st.cache_data.clear()
                    else:
                        st.error(f"Promotion failed: {msg}")
