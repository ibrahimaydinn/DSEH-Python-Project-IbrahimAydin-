"""
Page "Fleet overview": the key numbers and the monthly trends of the whole fleet.
"""

import streamlit as st

from karpowership import plots
from karpowership.calculations import summarize, summarize_by
from karpowership.data import add_month, monthly_table
from pages.shared import selected_data, show, show_kpis

st.title("Fleet overview")

# selected_data() returns a dictionary with the tables for the ships and dates
# chosen in the sidebar. We take out the two tables this page needs.
data = selected_data()
daily, events = data["daily"], data["events"]

# The eight headline numbers, calculated over all the selected ship-days.
show_kpis(summarize(daily))

# Group the days by month: one row per month for the whole fleet.
fleet_monthly = summarize_by(add_month(daily), ["month"])
show(plots.monthly_bars(fleet_monthly, "production_mwh", "Energy produced by the fleet each month", "MWh"))
show(plots.monthly_line(fleet_monthly, "availability", "Fleet availability", events, percent=True))
st.caption("Shaded: downtimes of 14 days or more.")

# Group by ship AND month (one row per ship per month), then turn it into a grid:
# one row per ship, one column per month. That grid is drawn as a heatmap.
ship_monthly = summarize_by(add_month(daily), ["ship_name", "month"])
show(plots.availability_heatmap(monthly_table(ship_monthly, "availability")))
st.caption("Each row is a ship, each column a month. White = always available, dark = down most of the month.")
