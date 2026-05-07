import streamlit as st

from theme import inject

st.set_page_config(
    page_title="Drift Triage Co-Pilot",
    page_icon="🚁",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject()

demo_page = st.Page("pages/demo.py",          title="Demo",          icon="🎬", default=True)
inv_page  = st.Page("pages/investigation.py", title="Investigation", icon="🔬")
sys_page  = st.Page("pages/system.py",        title="System",        icon="🛠")

pg = st.navigation([demo_page, inv_page, sys_page])
pg.run()
