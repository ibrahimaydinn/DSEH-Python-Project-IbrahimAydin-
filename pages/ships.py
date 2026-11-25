"""
Page "Ships": compare the ships, then look at one ship in detail.
"""

import streamlit as st

from karpowership import plots
from karpowership.calculations import summarize, summarize_by
from karpowership.fleet import get_ship
from pages.shared import DATE_COLUMNS, selected_data, show, show_kpis

st.title("Ships")
data = selected_data()
daily, events, check = data["daily"], data["events"], data["check"]

# --- Comparison -----------------------------------------------------------------
st.header("Comparison")
table = summarize_by(daily, ["ship_name"])
st.dataframe(
    table[["ship_name", "production_mwh", "fuel_ton", "mwh_per_ton", "capacity_factor",
           "availability", "downtime_days", "fuel_cost_per_mwh", "margin"]],
    hide_index=True,
    column_config={
        "ship_name": "Ship",
        "production_mwh": st.column_config.NumberColumn("Energy (MWh)", format="%,.0f"),
        "fuel_ton": st.column_config.NumberColumn("Fuel (t)", format="%,.0f"),
        "mwh_per_ton": st.column_config.NumberColumn("MWh/t", format="%.2f"),
        "capacity_factor": st.column_config.NumberColumn("Capacity factor", format="percent"),
        "availability": st.column_config.NumberColumn("Availability", format="percent"),
        "downtime_days": "Downtime days",
        "fuel_cost_per_mwh": st.column_config.NumberColumn("Fuel cost $/MWh", format="%.1f"),
        "margin": st.column_config.NumberColumn("Margin", format="percent"),
    },
)

charts = {
    "Efficiency (MWh per tonne)": ("mwh_per_ton", "{:.2f}"),
    "Capacity factor": ("capacity_factor", "{:.1%}"),
    "Availability": ("availability", "{:.1%}"),
    "Energy produced (MWh)": ("production_mwh", "{:,.0f}"),
}
choice = st.radio("Compare by", list(charts), horizontal=True)
column, number_format = charts[choice]
show(plots.ship_bars(table, column, choice, number_format))

# --- One ship ---------------------------------------------------------------------
st.header("One ship in detail")
ships = sorted(daily["ship_name"].unique())
ship = st.selectbox("Ship", ships, index=ships.index("Rauf Bey") if "Rauf Bey" in ships else 0)
info = get_ship(ship)
st.caption(f"{info.site} · {info.capacity_mw:.0f} MW · design efficiency {info.design_mwh_per_ton} MWh/t")

ship_days = daily[daily["ship_name"] == ship]
ship_events = events[events["ship_name"] == ship]
show_kpis(summarize(ship_days))
show(plots.daily_production(ship_days, ship_events))
show(plots.efficiency_vs_normal(check[check["ship_name"] == ship], ship_events))
st.caption("Grey dots: daily efficiency. Blue line: last 7 days. Dashed line: normal level "
           "(median of the previous 60 days). Red triangles: more than 4% below normal.")

st.subheader("Downtime of this ship")
if ship_events.empty:
    st.write("No downtime in this period.")
else:
    st.dataframe(ship_events, hide_index=True, column_config=DATE_COLUMNS)
