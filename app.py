"""
Karpowership Fleet Dashboard - Streamlit entry point.

This file only sets up the app: the page settings, the sidebar with the
selection form and the list of pages. The content of each page lives in the
``pages/`` folder, and all calculations live in the ``karpowership`` package.

Run with:  streamlit run app.py
"""

import streamlit as st

st.set_page_config(page_title="Karpowership Fleet Dashboard", layout="wide")

# Hide the buttons in the top-right corner (share, menu with record / print /
# theme settings) and the download / fullscreen buttons on charts and tables.
# The top bar itself stays, because it holds the button that re-opens the sidebar.
st.markdown("""
<style>
[data-testid="stToolbarActions"], [data-testid="stMainMenu"], [data-testid="stAppDeployButton"],
[data-testid="stDecoration"], #MainMenu, footer { display: none !important; }
[data-testid="stElementToolbar"], .vega-embed details { display: none !important; }
</style>
""", unsafe_allow_html=True)

pages = [
    st.Page("pages/overview.py", title="Fleet overview", default=True),
    st.Page("pages/ships.py", title="Ships"),
    st.Page("pages/statistics.py", title="Statistics"),
    st.Page("pages/downtime.py", title="Downtime and alerts"),
    st.Page("pages/data.py", title="Data"),
]
page = st.navigation(pages)

# The selection form is shown under the page list on every page.
from pages.shared import selection_form  # noqa: E402  (needs st.set_page_config first)

selection_form()

if st.session_state.get("selection") is None:
    st.title("Fleet operations dashboard")
    st.write("Choose the ships, dates and prices in the sidebar, then click **Show selected data**.")
else:
    page.run()
