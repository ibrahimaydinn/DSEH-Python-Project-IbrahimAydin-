"""
Page "Statistics": numbers computed with numpy and scipy (see ``karpowership/analysis.py``).
"""

import streamlit as st

from karpowership import analysis, plots
from pages.shared import selected_data, show

st.title("Statistics")
data = selected_data()
daily, events = data["daily"], data["events"]

st.header("How efficient and how stable is each ship?")
st.write("Daily efficiency on normal operating days. A low *variation* means the ship runs steadily.")
st.dataframe(analysis.efficiency_statistics(daily), hide_index=True, column_config={
    "ship_name": "Ship", "days": "Days", "mean": "Mean MWh/t", "std": "Std", "p10": "10th pct",
    "median": "Median", "p90": "90th pct",
    "variation_pct": st.column_config.NumberColumn("Variation %", format="%.1f"),
})
show(plots.efficiency_boxplot(daily))

st.header("Is there a seasonal pattern?")
show(plots.seasonal_line(analysis.seasonal_profile(daily)))
st.caption("Demand (and so the capacity factor) is higher in late spring and summer.")

st.header("Is efficiency changing over time?")
st.write("A straight line fitted through each ship's monthly efficiency (linear regression). "
         "A p-value below 0.05 means the trend is unlikely to be random.")
st.dataframe(analysis.efficiency_trend(daily), hide_index=True, column_config={
    "ship_name": "Ship", "months": "Months",
    "change_per_year": st.column_config.NumberColumn("Change per year (MWh/t)", format="%+.3f"),
    "r_squared": st.column_config.NumberColumn("R²", format="%.2f"),
    "p_value": st.column_config.NumberColumn("p-value", format="%.3f"),
})

st.header("Was there a warning before each long downtime?")
st.write("Efficiency in the 3 weeks before the downtime compared with the 2 months before that (t-test). "
         "*Significant* means the drop is real, not chance: the ship gave a warning sign.")
test = analysis.before_downtime_test(daily, events)
if test.empty:
    st.write("No long downtime in the selected period.")
else:
    st.dataframe(test, hide_index=True, column_config={
        "ship_name": "Ship", "downtime": "Downtime",
        "normal_mwh_per_ton": st.column_config.NumberColumn("Normal MWh/t", format="%.2f"),
        "before_mwh_per_ton": st.column_config.NumberColumn("Before downtime MWh/t", format="%.2f"),
        "change_pct": st.column_config.NumberColumn("Change %", format="%+.1f"),
        "p_value": st.column_config.NumberColumn("p-value", format="%.4f"),
        "significant": "Significant",
    })
