"""The five dashboard tabs. Each function draws one tab."""
import pandas as pd
import streamlit as st

from src import analytics, charts
from src.calculations import add_period, summarize, summarize_by
from src.data import OPERATING, to_excel_bytes
from src.fleet import get_ship

# Show dates without the time part in tables.
DATES = {col: st.column_config.DateColumn(format="DD MMM YYYY") for col in ["start", "end", "from", "to", "date"]}


def show_kpis(summary: dict) -> None:
    """Eight headline numbers in two rows."""
    row1 = st.columns(4)
    row1[0].metric("Energy produced", f"{summary['production_mwh']:,.0f} MWh")
    row1[1].metric("Fuel consumed", f"{summary['fuel_ton']:,.0f} t")
    row1[2].metric("Efficiency", f"{summary['mwh_per_ton']:.2f} MWh/t", help="Total MWh / total fuel")
    row1[3].metric("Capacity factor", f"{summary['capacity_factor']:.1%}", help="MWh produced / maximum possible MWh")
    row2 = st.columns(4)
    row2[0].metric("Availability", f"{summary['availability']:.1%}", help="Share of days the ship could produce")
    row2[1].metric("Downtime days", f"{summary['downtime_days']}")
    row2[2].metric("CO₂ per MWh", f"{summary['co2_per_mwh']:.3f} t")
    row2[3].metric("Profit (after fuel)", f"${summary['profit']:,.0f}", help="Revenue - fuel cost")


# ---------------------------------------------------------------- Tab 1
def fleet_overview(df: pd.DataFrame, events: pd.DataFrame, alerts: pd.DataFrame, period: str) -> None:
    # A plain box for each long downtime, with the early warning if there was one.
    for _, e in events[events["days"] >= 14].iterrows():
        text = (f"**{e['ship_name']} – {e['type']}** from {e['start']:%d %b} to {e['end']:%d %b %Y} "
                f"({e['days']} days): {e['cause']}. About **{e['lost_mwh']:,.0f} MWh** not produced "
                f"(about ${e['lost_revenue']:,.0f} of revenue).")
        warning = alerts[(alerts["ship_name"] == e["ship_name"]) & (alerts["followed_by"] != "")]
        if not warning.empty:
            w = warning.iloc[0]
            text += (f" Efficiency started dropping on {w['from']:%d %b} "
                     f"({w['warning_days_before']} days before), worst {w['worst_drop']:.1%}.")
        with st.container(border=True):
            st.markdown(text)

    show_kpis(summarize(df))

    by_period = add_period(df, period)
    per_ship = summarize_by(by_period, ["period", "ship_name"])
    fleet = summarize_by(by_period, ["period"])

    st.subheader("Energy produced by each ship")
    st.bar_chart(per_ship, x="period", y="production_mwh", color="ship_name", x_label="", y_label="MWh")

    left, right = st.columns(2)
    with left:
        st.subheader("Fleet efficiency")
        st.altair_chart(charts.line_with_downtime(fleet, "mwh_per_ton", "MWh per tonne", events))
    with right:
        st.subheader("Fleet availability")
        st.altair_chart(charts.line_with_downtime(fleet, "availability", "Availability", events, percent=True))
    st.caption("Shaded: red = outage, blue = maintenance, orange = idle. One ship's downtime mostly shows up in availability; "
               "fleet efficiency only moves a little because the other ships keep running normally.")

    st.subheader("Status of each ship, day by day")
    st.altair_chart(charts.status_timeline(df))


# ---------------------------------------------------------------- Tab 2
def compare_ships(df: pd.DataFrame, period: str) -> None:
    table = summarize_by(df, ["ship_name"])
    table["capacity_mw"] = table["ship_name"].map(lambda name: get_ship(name).capacity_mw)
    st.subheader("Ship by ship")
    st.dataframe(
        table[["ship_name", "capacity_mw", "production_mwh", "fuel_ton", "mwh_per_ton",
               "capacity_factor", "availability", "downtime_days", "fuel_cost_per_mwh", "margin"]],
        hide_index=True,
        column_config={
            "ship_name": "Ship",
            "capacity_mw": "MW",
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

    per_ship = summarize_by(add_period(df, period), ["period", "ship_name"])
    st.subheader("Efficiency over time (MWh per tonne)")
    st.line_chart(per_ship, x="period", y="mwh_per_ton", color="ship_name", x_label="", y_label="MWh/t")
    st.caption("A ship that is down for a whole period shows 0: it burned standby fuel but produced nothing.")

    st.subheader("Capacity factor over time")
    st.line_chart(per_ship, x="period", y="capacity_factor", color="ship_name", x_label="", y_label="")


# ---------------------------------------------------------------- Tab 3
def ship_details(df: pd.DataFrame, records: pd.DataFrame, events: pd.DataFrame, check: pd.DataFrame,
                 fuel_price: float) -> None:
    ships = sorted(df["ship_name"].unique())
    ship = st.selectbox("Ship", ships, index=ships.index("Rauf Bey") if "Rauf Bey" in ships else 0)
    info = get_ship(ship)
    st.caption(f"{info.site} · {info.capacity_mw:.0f} MW · design efficiency {info.design_mwh_per_ton} MWh/t")

    ship_days = df[df["ship_name"] == ship]
    ship_events = events[events["ship_name"] == ship]
    show_kpis(summarize(ship_days))

    st.subheader("Daily production")
    st.bar_chart(ship_days, x="date", y="production_mwh", x_label="", y_label="MWh")

    st.subheader("Efficiency compared with normal")
    st.altair_chart(charts.efficiency_chart(check[check["ship_name"] == ship], ship_events))
    st.caption("Grey dots: daily efficiency. Blue line: last 7 days. Dashed line: normal level "
               f"(median of the previous 60 days). Red triangles: more than {analytics.DROP_THRESHOLD:.0%} below normal.")

    st.subheader("Downtime")
    if ship_events.empty:
        st.write("No downtime in this period.")
    else:
        st.dataframe(ship_events, hide_index=True, column_config=DATES)

    with st.expander("Look up a single day"):
        day = st.date_input("Date", value=ship_days["date"].max(),
                            min_value=ship_days["date"].min(), max_value=ship_days["date"].max())
        rows = records[(records["ship_name"] == ship) & (records["date"] == pd.Timestamp(day))]
        if rows.empty:
            st.write("No record for this day.")
        else:
            st.dataframe(rows, hide_index=True, column_config=DATES)
            mwh, fuel = rows["production_mwh"].sum(), rows["fuel_consumption_ton"].sum()
            if mwh > 0:
                st.write(f"Efficiency: **{mwh / fuel:.2f} MWh/t** · break-even electricity price: "
                         f"**${fuel * fuel_price / mwh:,.0f}/MWh**")


# ---------------------------------------------------------------- Tab 4
def downtime_and_alerts(df: pd.DataFrame, records: pd.DataFrame, events: pd.DataFrame,
                        alerts: pd.DataFrame, fuel_price: float) -> None:
    st.subheader("Downtime periods")
    cols = st.columns(3)
    cols[0].metric("Downtime days", f"{events['days'].sum()}")
    cols[1].metric("Energy not produced", f"{events['lost_mwh'].sum():,.0f} MWh")
    cols[2].metric("Revenue missed", f"${events['lost_revenue'].sum():,.0f}")
    st.dataframe(events, hide_index=True, column_config=DATES)
    st.caption("Energy not produced = days down × the ship's usual daily output in the 30 days before.")

    st.subheader("Efficiency alerts")
    st.write(f"Periods where a ship's 7-day efficiency was more than {analytics.DROP_THRESHOLD:.0%} "
             "below its normal level. If a downtime followed, the alert was an early warning.")
    if alerts.empty:
        st.write("No alerts.")
    else:
        st.dataframe(alerts, hide_index=True,
                     column_config={**DATES, "worst_drop": st.column_config.NumberColumn(format="percent")})

    st.subheader("Fuel savings potential")
    st.write("Extra fuel burned because ships ran below their design efficiency (operating days only).")
    savings = analytics.fuel_savings(df, fuel_price)
    st.metric("Total extra fuel cost", f"${savings['extra_cost_usd'].sum():,.0f}")
    st.dataframe(savings, hide_index=True)

    st.subheader("Data checks")
    st.dataframe(analytics.data_checks(records, df), hide_index=True)


# ---------------------------------------------------------------- Tab 5
def data_tab(records: pd.DataFrame) -> None:
    st.subheader("Add a record")
    with st.form("add_record", clear_on_submit=True):
        ship = st.text_input("Ship name", value="Rauf Bey", help="A new name adds a new ship (25 MW by default).")
        day = st.date_input("Date", value=records["date"].max())
        mwh = st.number_input("Production (MWh)", min_value=0.0, value=350.0)
        fuel = st.number_input("Fuel (t)", min_value=0.0, value=70.0)
        status = st.selectbox("Status", [OPERATING, "ramp_up", "maintenance", "outage", "idle"])
        note = st.text_input("Note")
        if st.form_submit_button("Add"):
            st.session_state.added_records.append({
                "ship_name": ship.strip(), "date": pd.Timestamp(day), "production_mwh": mwh,
                "fuel_consumption_ton": fuel, "status": status, "event_note": note, "source": "manual",
            })
            st.rerun()

    st.subheader("Download")
    left, right = st.columns(2)
    left.download_button("Excel", to_excel_bytes(records), "powership_data.xlsx")
    csv = records.assign(date=records["date"].dt.date).to_csv(index=False)
    right.download_button("CSV", csv, "powership_data.csv")

    st.subheader("All records")
    st.dataframe(records, hide_index=True, column_config=DATES)
