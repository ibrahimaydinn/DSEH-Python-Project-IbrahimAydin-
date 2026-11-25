"""The few charts that need shaded downtime periods (built with Altair).

Simple charts use Streamlit's built-in st.bar_chart / st.line_chart instead.
"""
import altair as alt
import pandas as pd

STATUS_COLORS = {
    "operating": "#c8c8c8",  # grey: normal, so problems stand out
    "ramp_up": "#8cb8f0",
    "maintenance": "#2f6fce",
    "outage": "#d93b3b",
    "no_data": "#f0f0f0",
}
EVENT_COLORS = alt.Scale(domain=["Outage", "Maintenance"], range=["#d93b3b", "#2f6fce"])


def downtime_bands(events: pd.DataFrame) -> alt.Chart:
    """Shaded rectangles: red = outage, blue = maintenance."""
    events = events.assign(end_next_day=events["end"] + pd.Timedelta(days=1))
    return alt.Chart(events).mark_rect(opacity=0.15).encode(
        x="start:T",
        x2="end_next_day:T",
        fill=alt.Fill("type:N", scale=EVENT_COLORS, title="Downtime"),
        tooltip=["ship_name:N", "type:N", "cause:N", "start:T", "end:T", "days:Q"],
    )


def line_with_downtime(df: pd.DataFrame, y: str, title: str, events: pd.DataFrame,
                       percent: bool = False) -> alt.LayerChart:
    """A single line over time, with downtime periods shaded behind it."""
    axis = alt.Axis(format=".0%") if percent else alt.Axis()
    line = alt.Chart(df).mark_line(point=True).encode(
        x=alt.X("period:T", title=None),
        y=alt.Y(f"{y}:Q", title=title, axis=axis, scale=alt.Scale(zero=False)),
        tooltip=[alt.Tooltip("period:T"), alt.Tooltip(f"{y}:Q", format=".1%" if percent else ".2f")],
    )
    return (downtime_bands(events) + line).properties(height=260)


def status_timeline(df: pd.DataFrame) -> alt.Chart:
    """One row per ship, one coloured cell per day."""
    df = df.assign(next_day=df["date"] + pd.Timedelta(days=1))
    return alt.Chart(df).mark_rect().encode(
        x=alt.X("date:T", title=None),
        x2="next_day:T",
        y=alt.Y("ship_name:N", title=None),
        color=alt.Color("status:N", title="Status",
                        scale=alt.Scale(domain=list(STATUS_COLORS), range=list(STATUS_COLORS.values()))),
        tooltip=["ship_name", "date:T", "status", "event_note", "production_mwh", "fuel_consumption_ton"],
    ).properties(height=alt.Step(22))


def efficiency_chart(check: pd.DataFrame, events: pd.DataFrame) -> alt.LayerChart:
    """Daily efficiency (dots), last-7-days efficiency (line) and the normal level (dashed)."""
    dots = alt.Chart(check).mark_circle(color="#999999", opacity=0.5).encode(
        x=alt.X("date:T", title=None),
        y=alt.Y("mwh_per_ton:Q", title="Efficiency (MWh per tonne)", scale=alt.Scale(zero=False)),
        tooltip=["date:T", alt.Tooltip("mwh_per_ton:Q", format=".2f")],
    )
    recent = alt.Chart(check).mark_line(color="#2f6fce", strokeWidth=2).encode(x="date:T", y="recent:Q")
    normal = alt.Chart(check).mark_line(color="#333333", strokeDash=[5, 3]).encode(x="date:T", y="normal:Q")
    alerts = alt.Chart(check[check["alert"]]).mark_point(shape="triangle-down", color="#d93b3b", filled=True,
                                                          size=60).encode(
        x="date:T", y="recent:Q",
        tooltip=["date:T", alt.Tooltip("change:Q", format="+.1%", title="vs normal")],
    )
    return (downtime_bands(events) + dots + normal + recent + alerts).properties(height=280)
