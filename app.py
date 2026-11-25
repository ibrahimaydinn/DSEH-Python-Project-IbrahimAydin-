"""Karowership fleet dashboard.

Run with:  streamlit run app.py

How the page is built:
  1. Sidebar: choose the data and the scenario
  2. Load or simulate the records
  3. Add the daily metrics and find downtime and efficiency alerts
  4. Draw the five tabs
"""
from datetime import date

import pandas as pd
import streamlit as st

from src import analytics, views
from src.calculations import add_daily_metrics
from src.data import MAINTENANCE, ORIGINAL_FILE, OUTAGE, load_file, one_row_per_day, prepare
from src.fleet import ALL_SHIPS
from src.simulation import DEFAULT_EVENT, Event, generate_fleet

st.set_page_config(page_title="Karowership Fleet Dashboard", page_icon="⚡", layout="wide")

if "added_records" not in st.session_state:
    st.session_state.added_records = []  # records typed in on the Data tab


@st.cache_data
def load_original() -> pd.DataFrame:
    return load_file(ORIGINAL_FILE)


@st.cache_data
def simulate(end: date, ship: str, kind: str, start: date, days: int, new_ships: bool, seed: int) -> pd.DataFrame:
    events = [] if ship == "None" else [Event(ship, start, days, kind=kind,
                                              cause=DEFAULT_EVENT.cause if kind == OUTAGE else "Dry-docking")]
    return generate_fleet(load_original(), end, events, new_ships=new_ships, seed=seed)


# ---------------------------------------------------------------- 1. Sidebar
st.sidebar.title("⚡ Karowership")
source = st.sidebar.radio("Data", ["Simulated fleet", "Original Excel only"])

if source == "Simulated fleet":
    st.sidebar.subheader("Downtime scenario")
    ship = st.sidebar.selectbox("Ship", ["None"] + list(ALL_SHIPS), index=3)  # default: Rauf Bey
    kind = st.sidebar.radio("Type", [OUTAGE, MAINTENANCE], format_func=str.capitalize, horizontal=True)
    start = st.sidebar.date_input("Start", value=DEFAULT_EVENT.start)
    days = st.sidebar.slider("Days", 1, 120, DEFAULT_EVENT.days)

    st.sidebar.subheader("Simulation")
    new_ships = st.sidebar.checkbox("Include the 4 new ships", value=True)
    end = st.sidebar.date_input("Simulate until", value=date(2024, 12, 31), min_value=date(2024, 4, 30))
    seed = st.sidebar.number_input("Random seed", value=42, help="Change it to get different random data.")
    records = simulate(end, ship, kind, start, days, new_ships, seed)
else:
    records = load_original()

if st.session_state.added_records:
    records = prepare(pd.concat([records, pd.DataFrame(st.session_state.added_records)]))

st.sidebar.subheader("Filters")
all_ships = sorted(records["ship_name"].unique())
ships = st.sidebar.multiselect("Ships", all_ships, default=all_ships)
first_day, last_day = records["date"].min().date(), records["date"].max().date()
date_range = st.sidebar.date_input("Dates", value=(first_day, last_day), min_value=first_day, max_value=last_day)
period = st.sidebar.radio("Group by", ["W", "M"], format_func={"W": "Week", "M": "Month"}.get, horizontal=True)

st.sidebar.subheader("Prices (placeholders)")
fuel_price = st.sidebar.number_input("Fuel (USD per tonne)", value=450.0, step=10.0)
electricity_price = st.sidebar.number_input("Electricity (USD per MWh)", value=100.0, step=5.0)

# ---------------------------------------------------------------- 2-3. Prepare the data
daily = add_daily_metrics(one_row_per_day(records), fuel_price, electricity_price)
daily = daily[daily["ship_name"].isin(ships)]

# Alerts need the days before the selected range, so they use all dates.
events = analytics.downtime_events(daily, electricity_price)
check = analytics.efficiency_check(daily)
alerts = analytics.efficiency_alerts(check, events)

if len(date_range) == 2:
    from_day, to_day = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1])
    daily = daily[daily["date"].between(from_day, to_day)]
    events = events[(events["end"] >= from_day) & (events["start"] <= to_day)]
    alerts = alerts[(alerts["to"] >= from_day) & (alerts["from"] <= to_day)]
    check = check[check["date"].between(from_day, to_day)]

if daily.empty:
    st.warning("No data for this selection.")
    st.stop()

# ---------------------------------------------------------------- 4. Tabs
st.title("Fleet operations dashboard")
st.caption(f"{source} · {daily['ship_name'].nunique()} ships · "
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
