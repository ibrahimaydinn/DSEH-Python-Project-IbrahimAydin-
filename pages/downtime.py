"""
Page "Downtime and alerts": downtime periods, efficiency alerts, fuel savings and data checks.
"""

import streamlit as st

from karpowership import alerts, plots
from pages.shared import DATE_COLUMNS, selected_data, show

st.title("Downtime and alerts")
data = selected_data()
daily, events, alert_periods = data["daily"], data["events"], data["alerts"]
fuel_price = data["prices"][0]

st.header("Downtime periods")
columns = st.columns(3)
columns[0].metric("Downtime days", f"{events['days'].sum()}")
columns[1].metric("Energy not produced", f"{events['lost_mwh'].sum():,.0f} MWh")
columns[2].metric("Revenue missed", f"${events['lost_revenue'].sum():,.0f}")
st.dataframe(events, hide_index=True, column_config=DATE_COLUMNS)
st.caption("Energy not produced = days down × the ship's usual daily output in the 30 days before.")

st.header("Efficiency alerts")
st.write("Periods where a ship's 7-day efficiency was more than 4% below its normal level. "
         "If a downtime followed, the alert was an early warning.")
if alert_periods.empty:
    st.write("No alerts.")
else:
    st.dataframe(alert_periods, hide_index=True,
                 column_config={**DATE_COLUMNS, "worst_drop": st.column_config.NumberColumn(format="percent")})

st.header("Fuel savings potential")
st.write("Extra fuel burned because ships ran below their design efficiency (operating days only).")
savings = alerts.fuel_savings(daily, fuel_price)
st.metric("Total extra fuel cost", f"${savings['extra_cost_usd'].sum():,.0f}")
show(plots.ship_bars(savings, "extra_cost_usd", "Extra fuel cost per ship (USD)", "${:,.0f}"))

st.header("Data checks")
st.dataframe(alerts.data_checks(data["records"], daily), hide_index=True)
