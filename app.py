"""Powership efficiency dashboard (Streamlit)."""
import streamlit as st

from src.calculations import add_record_metrics, summarize
from src.data import load_data

st.set_page_config(page_title="Powership Efficiency", page_icon="⚡", layout="centered")


@st.cache_data
def get_data():
    return load_data()


df, n_removed = get_data()

st.title("⚡ Powership Efficiency Calculator")
st.caption("Select a ship and a date to see fuel efficiency and operating margin.")

# ---------- Sidebar: inputs ----------
with st.sidebar:
    st.header("Selection")
    ship = st.selectbox("Ship", sorted(df["ship_name"].unique()))
    ship_df = df[df["ship_name"] == ship]
    date = st.date_input(
        "Date",
        value=ship_df["date"].min(),
        min_value=ship_df["date"].min(),
        max_value=ship_df["date"].max(),
    )

    st.header("Price assumptions")
    fuel_price = st.number_input("Fuel price (USD/ton)", min_value=1.0, value=450.0, step=10.0)
    elec_price = st.number_input("Electricity price (USD/MWh)", min_value=0.0, value=100.0, step=5.0)
    st.caption("Placeholders. Replace with real prices.")

# ---------- Results ----------
day_df = ship_df[ship_df["date"] == date]
period = summarize(ship_df, fuel_price, elec_price)

st.subheader(f"{ship} on {date:%d %b %Y}")

if day_df.empty:
    st.warning("No valid record for this ship on this date (missing or removed). Pick another date.")
    st.stop()

day = summarize(day_df, fuel_price, elec_price)

c1, c2, c3 = st.columns(3)
c1.metric(
    "Efficiency (MWh/ton)",
    f"{day['mwh_per_ton']:.2f}",
    delta=f"{day['mwh_per_ton'] - period['mwh_per_ton']:+.2f} vs period avg",
)
c2.metric("Electricity produced", f"{day['mwh']:,.1f} MWh")
c3.metric("Fuel used", f"{day['fuel_t']:,.1f} t")

c4, c5, c6 = st.columns(3)
c4.metric("Revenue", f"${day['revenue']:,.0f}")
c5.metric("Fuel cost", f"${day['fuel_cost']:,.0f}")
c6.metric("Profit", f"${day['profit']:,.0f}", delta=f"{day['margin']:.1%} margin")

st.write(f"**Break-even electricity price:** ${day['breakeven']:,.0f}/MWh")

if len(day_df) > 1:
    st.info(
        f"This ship has {len(day_df)} records on this date. "
        "The figures above combine them; the individual records are shown below."
    )
    st.dataframe(
        add_record_metrics(day_df, fuel_price, elec_price)[
            ["production_mwh", "fuel_consumption_ton", "mwh_per_ton", "profit"]
        ].round(2),
        hide_index=True,
    )

# ---------- Context ----------
st.divider()
st.subheader(f"{ship}: full period")
trend = ship_df.groupby("date", as_index=False).agg(
    production_mwh=("production_mwh", "sum"),
    fuel_consumption_ton=("fuel_consumption_ton", "sum"),
)
trend["MWh per ton"] = trend["production_mwh"] / trend["fuel_consumption_ton"]
st.line_chart(trend.set_index("date")["MWh per ton"])
st.caption(
    f"Period average: {period['mwh_per_ton']:.2f} MWh/ton | total profit: ${period['profit']:,.0f} "
    f"| {n_removed} rows with missing values were excluded."
)
