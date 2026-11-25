"""Karpowership fleet dashboard.

Run with:  streamlit run app.py

How the page is built:
  1. Load the data (2024 to November 2026)
  2. Sidebar: choose ships, dates and prices, then click "Show selected data"
  3. Add the daily metrics and find downtime and efficiency alerts
  4. Draw the five tabs
"""
import pandas as pd
import streamlit as st

from src import analytics, views
from src.calculations import add_daily_metrics
from src.data import one_row_per_day, prepare
from src.simulation import LAST_DAY, SIMULATION_START, build_dataset

st.set_page_config(page_title="Karpowership Fleet Dashboard", layout="wide")

# Hide the top-right toolbar (share, menu, record, print, theme settings) and
# the download / fullscreen buttons that appear on charts and tables.
st.markdown("""
<style>
[data-testid="stToolbar"], [data-testid="stDecoration"], #MainMenu, footer { display: none !important; }
[data-testid="stElementToolbar"], .vega-embed details { display: none !important; }
</style>
""", unsafe_allow_html=True)

if "added_records" not in st.session_state:
    st.session_state.added_records = []  # records typed in on the Data tab
if "show_data" not in st.session_state:
    st.session_state.show_data = False  # becomes True after the first click


@st.cache_data
def load_data() -> pd.DataFrame:
    return build_dataset()


# ---------------------------------------------------------------- 1. Data
records = load_data()
if st.session_state.added_records:
    records = prepare(pd.concat([records, pd.DataFrame(st.session_state.added_records)]))

# ---------------------------------------------------------------- 2. Sidebar
# A form: the choices are only applied when the button is clicked.
st.sidebar.title("Karpowership")
with st.sidebar.form("selection"):
    all_ships = sorted(records["ship_name"].unique())
    ships = st.multiselect("Ships", all_ships, default=all_ships)
    date_range = st.date_input("Dates", value=(SIMULATION_START, LAST_DAY),
                               min_value=SIMULATION_START, max_value=LAST_DAY)
    period = st.radio("Group by", ["W", "M"], index=1, format_func={"W": "Week", "M": "Month"}.get,
                      horizontal=True)
    fuel_price = st.number_input("Fuel price (USD per tonne)", value=450.0, step=10.0)
    electricity_price = st.number_input("Electricity price (USD per MWh)", value=100.0, step=5.0)
    if st.form_submit_button("Show selected data", type="primary", width="stretch"):
        st.session_state.show_data = True

st.title("Fleet operations dashboard")
if not st.session_state.show_data:
    st.write("Choose the ships, dates and prices in the sidebar, then click **Show selected data**.")
    st.stop()
if not ships or len(date_range) != 2:
    st.write("Select at least one ship and a start and end date.")
    st.stop()

# ---------------------------------------------------------------- 3. Prepare the data
daily = add_daily_metrics(one_row_per_day(records), fuel_price, electricity_price)
daily = daily[daily["ship_name"].isin(ships)]

# Alerts need the days before the selected range, so they use all dates.
events = analytics.downtime_events(daily, electricity_price)
check = analytics.efficiency_check(daily)
alerts = analytics.efficiency_alerts(check, events)

from_day, to_day = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1])
daily = daily[daily["date"].between(from_day, to_day)]
events = events[(events["end"] >= from_day) & (events["start"] <= to_day)]
alerts = alerts[(alerts["to"] >= from_day) & (alerts["from"] <= to_day)]
check = check[check["date"].between(from_day, to_day)]

if daily.empty:
    st.write("No data for this selection.")
    st.stop()

# ---------------------------------------------------------------- 4. Tabs
st.caption(f"{daily['ship_name'].nunique()} ships · "
           f"{daily['date'].min():%d %b %Y} – {daily['date'].max():%d %b %Y}")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["Fleet overview", "Compare ships", "Ship details",
                                        "Downtime & alerts", "Data"])
with tab1:
    views.fleet_overview(daily, events, alerts, period)
with tab2:
    views.compare_ships(daily, period)
with tab3:
    views.ship_details(daily, records, events, check, fuel_price)
with tab4:
    views.downtime_and_alerts(daily, records, events, alerts, fuel_price)
with tab5:
    views.data_tab(records)
