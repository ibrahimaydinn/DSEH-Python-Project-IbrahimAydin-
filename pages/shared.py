"""
Helpers shared by all the pages: the sidebar form and the selected data.

This is not a page itself (it is not listed in ``app.py``).
"""

from datetime import date

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from karpowership import alerts
from karpowership.calculations import add_daily_metrics
from karpowership.data import load_records, one_row_per_day, prepare

FIRST_DAY, LAST_DAY = date(2024, 1, 1), date(2026, 11, 30)


@st.cache_data
def daily_table(fuel_price, electricity_price, added_records):
    """All records (file + records added on the Data page), one row per ship and day."""
    records = load_records()
    if added_records:
        records = prepare(pd.concat([records, pd.DataFrame(added_records)]))
    return records, add_daily_metrics(one_row_per_day(records), fuel_price, electricity_price)


def selection_form():
    """The sidebar form. The choices are only applied when the button is clicked."""
    st.session_state.setdefault("added_records", [])
    ship_names = sorted(daily_table(450.0, 100.0, st.session_state.added_records)[1]["ship_name"].unique())

    with st.sidebar.form("sidebar_form"):
        ships = st.multiselect("Ships", ship_names, default=ship_names)
        dates = st.date_input("Dates", value=(FIRST_DAY, LAST_DAY), min_value=FIRST_DAY, max_value=LAST_DAY)
        fuel_price = st.number_input("Fuel price (USD per tonne)", value=450.0, step=10.0)
        electricity_price = st.number_input("Electricity price (USD per MWh)", value=100.0, step=5.0)
        if st.form_submit_button("Show selected data", type="primary", width="stretch"):
            st.session_state.selection = {"ships": ships, "dates": dates, "fuel_price": fuel_price,
                                          "electricity_price": electricity_price}


def selected_data():
    """
    The data for the current selection.

    Returns a dictionary with:
        records  all raw records
        daily    one row per ship and day, only the selected ships and dates
        events   downtime periods       check   daily efficiency vs normal
        alerts   efficiency alert periods
        prices   (fuel price, electricity price)
    """
    choice = st.session_state.selection
    if not choice["ships"] or len(choice["dates"]) != 2:
        st.write("Select at least one ship and a start and end date in the sidebar.")
        st.stop()

    with st.spinner("Loading the selected data..."):
        records, daily = daily_table(choice["fuel_price"], choice["electricity_price"],
                                     st.session_state.added_records)
        daily = daily[daily["ship_name"].isin(choice["ships"])]

        # Alerts need the days before the selected range, so they use all dates first.
        events = alerts.downtime_events(daily, choice["electricity_price"])
        check = alerts.efficiency_check(daily)
        alert_periods = alerts.efficiency_alerts(check, events)

        start, end = pd.Timestamp(choice["dates"][0]), pd.Timestamp(choice["dates"][1])
        daily = daily[daily["date"].between(start, end)]
    if daily.empty:
        st.write("No data for this selection.")
        st.stop()

    return {
        "records": records,
        "daily": daily,
        "events": events[(events["end"] >= start) & (events["start"] <= end)],
        "check": check[check["date"].between(start, end)],
        "alerts": alert_periods[(alert_periods["to"] >= start) & (alert_periods["from"] <= end)],
        "prices": (choice["fuel_price"], choice["electricity_price"]),
    }


def show_kpis(summary):
    """Eight headline numbers in two rows (``summary`` comes from ``calculations.summarize``)."""
    row1 = st.columns(4)
    row1[0].metric("Energy produced (MWh)", f"{summary['production_mwh']:,.0f}")
    row1[1].metric("Fuel consumed (t)", f"{summary['fuel_ton']:,.0f}")
    row1[2].metric("Efficiency (MWh/t)", f"{summary['mwh_per_ton']:.2f}", help="Total MWh / total fuel")
    row1[3].metric("Capacity factor", f"{summary['capacity_factor']:.1%}", help="MWh produced / maximum possible MWh")
    row2 = st.columns(4)
    row2[0].metric("Availability", f"{summary['availability']:.1%}", help="Share of days the ship could produce")
    row2[1].metric("Downtime days", f"{summary['downtime_days']:.0f}")
    row2[2].metric("CO₂ per MWh (t)", f"{summary['co2_per_mwh']:.3f}")
    row2[3].metric("Profit after fuel (USD)", f"{summary['profit']:,.0f}", help="Revenue - fuel cost")


def show(fig):
    """Draw a matplotlib figure on the page, then free its memory."""
    st.pyplot(fig)
    plt.close(fig)


# Show dates without the time part in tables.
DATE_COLUMNS = {col: st.column_config.DateColumn(format="DD MMM YYYY") for col in ["start", "end", "from", "to", "date"]}
