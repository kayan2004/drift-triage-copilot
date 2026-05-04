import streamlit as st

st.set_page_config(
    page_title="Drift Triage Co-Pilot",
    layout="wide",
    initial_sidebar_state="expanded",
)

registry_page = st.Page("pages/registry.py", title="Model Registry", icon="📦")
investigations_page = st.Page("pages/investigations.py", title="Investigations", icon="🔍")
queue_page = st.Page("pages/queue_monitor.py", title="Queue Monitor", icon="📋")
hil_page = st.Page("pages/hil_inbox.py", title="HIL Inbox", icon="✅")

pg = st.navigation([registry_page, investigations_page, queue_page, hil_page])
pg.run()
