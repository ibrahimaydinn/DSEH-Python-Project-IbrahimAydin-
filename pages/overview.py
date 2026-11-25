"""
Page "Fleet overview": the long downtimes, the key numbers and the monthly trends.
"""

import streamlit as st

from karpowership import plots
from karpowership.calculations import summarize, summarize_by
from karpowership.data import add_month, monthly_table
from pages.shared import selected_data, show, show_kpis

st.title("Fleet overview")
data = selected_data()
daily, events, alerts = data["daily"], data["events"], data["alerts"]

# A plain box for each long downtime, with the early warning if there was one.
for _, event in events[events["days"] >= 14].iterrows():
    text = (f"**{event['ship_name']} – {event['type']}** from {event['start']:%d %b} to {event['end']:%d %b %Y} "
            f"({event['days']} days): {event['cause']}. About **{event['lost_mwh']:,.0f} MWh** not produced "
            f"(about ${event['lost_revenue']:,.0f} of revenue).")
    warning = alerts[(alerts["ship_name"] == event["ship_name"]) & (alerts["followed_by"] != "")]
    if not warning.empty:
        first = warning.iloc[0]
        text += (f" Efficiency started dropping on {first['from']:%d %b} "
                 f"({first['warning_days_before']} days before), worst {first['worst_drop']:.1%}.")
    with st.container(border=True):
        st.markdown(text)

show_kpis(summarize(daily))

fleet_monthly = summarize_by(add_month(daily), ["month"])
show(plots.monthly_bars(fleet_monthly, "production_mwh", "Energy produced by the fleet each month", "MWh"))
show(plots.monthly_line(fleet_monthly, "availability", "Fleet availability", events, percent=True))
st.caption("Shaded: long downtimes (14 days or more). One ship's downtime lowers the availability of the whole fleet.")

ship_monthly = summarize_by(add_month(daily), ["ship_name", "month"])
show(plots.availability_heatmap(monthly_table(ship_monthly, "availability")))
st.caption("Each row is a ship, each column a month. White = always available, dark = down most of the month.")
