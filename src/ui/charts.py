"""Altair chart builders. Pure functions: DataFrames in, charts out.

Colour rules: ships keep a fixed categorical colour (follows the ship, not its
rank); operational status uses a reserved palette that is never reused for
ships; normal operation is drawn neutral so exceptions stand out.
"""
from __future__ import annotations

import altair as alt
import pandas as pd

from src.schema import STATUS_LABELS, Status

# Validated categorical palette (fixed order), light and dark steps.
CATEGORICAL = {
    "light": ["#257de0", "#f47230", "#00b894", "#f2a600", "#ee7fac", "#008a17", "#6a4ce2", "#ec4647"],
    "dark": ["#338ced", "#e76624", "#00a888", "#d28e05", "#e24d8b", "#0aac23", "#9887ef", "#eb6263"],
}
NEUTRAL = {"light": "#c2c2c2", "dark": "#5a5a5a"}
MUTED = {"light": "#e3e3e3", "dark": "#303030"}
INK = {"light": "#191919", "dark": "#efefef"}
INK_2 = {"light": "#666666", "dark": "#9c9c9c"}

STATUS_COLORS = {
    Status.OPERATING: None,  # neutral, per theme
    Status.RAMP_UP: "#84b9f3",
    Status.TRIP: "#fbb315",
    Status.PLANNED_MAINTENANCE: "#2370cd",
    Status.DRY_DOCK: "#9887ef",
    Status.FORCED_OUTAGE: "#dc3c3d",
    Status.NO_DATA: None,  # muted, per theme
}
SEVERITY_COLORS = {"critical": "#dc3c3d", "warning": "#fbb315", "info": "#9c9c9c"}


class Theme:
    def __init__(self, mode: str, ships: list[str]):
        self.mode = mode if mode in ("light", "dark") else "light"
        palette = CATEGORICAL[self.mode]
        # >8 ships: wrap would repeat hues; fold extras into neutral instead.
        self.ship_colors = {s: (palette[i] if i < len(palette) else NEUTRAL[self.mode]) for i, s in enumerate(ships)}
        self.ships = ships

    def ship_scale(self, present: list[str] | None = None) -> alt.Scale:
        domain = [s for s in self.ships if present is None or s in present]
        return alt.Scale(domain=domain, range=[self.ship_colors[s] for s in domain])

    def status_scale(self) -> alt.Scale:
        domain = [STATUS_LABELS[s] for s in Status]
        rng = []
        for s in Status:
            c = STATUS_COLORS[s]
            if s == Status.OPERATING:
                c = NEUTRAL[self.mode]
            elif s == Status.NO_DATA:
                c = MUTED[self.mode]
            rng.append(c)
        return alt.Scale(domain=domain, range=rng)

    @property
    def ink(self) -> str:
        return INK[self.mode]

    @property
    def ink2(self) -> str:
        return INK_2[self.mode]


def _event_layers(events: pd.DataFrame, theme: Theme, y_label: bool = True, min_days: int = 1) -> list[alt.Chart]:
    """Shaded bands (and labels) for downtime events on a temporal x axis."""
    if events is None or events.empty:
        return []
    ev = events[events["days"] >= min_days].copy()
    if ev.empty:
        return []
    ev["end_excl"] = ev["end"] + pd.Timedelta(days=1)
    ev["label"] = ev["ship_name"] + ": " + ev["kind"].str.lower() + " (" + ev["days"].astype(str) + " d)"
    fill = alt.Fill("kind:N", scale=theme.status_scale(), legend=None)
    tooltip = [
        alt.Tooltip("ship_name:N", title="Ship"), alt.Tooltip("kind:N", title="Event"),
        alt.Tooltip("cause:N", title="Cause"), alt.Tooltip("start:T", title="Start"),
        alt.Tooltip("end:T", title="End"), alt.Tooltip("days:Q", title="Days"),
        alt.Tooltip("lost_mwh:Q", title="Est. lost MWh", format=",.0f"),
    ]
    band = alt.Chart(ev).mark_rect(opacity=0.14).encode(x="start:T", x2="end_excl:T", fill=fill, tooltip=tooltip)
    layers = [band]
    if y_label:
        big = ev[ev["days"] >= 14]
        if not big.empty:
            layers.append(
                alt.Chart(big).mark_text(align="left", baseline="top", dx=4, dy=4, fontSize=11, color=theme.ink2)
                .encode(x="start:T", y=alt.value(0), text="label:N")
            )
    return layers


def energy_by_ship(period: pd.DataFrame, theme: Theme, events: pd.DataFrame | None = None,
                   freq: str = "W") -> alt.Chart:
    """Stacked energy per ship; downtime of 14+ days shaded behind."""
    present = [s for s in theme.ships if s in set(period["ship_name"])]
    d = period.assign(ship_order=period["ship_name"].map({s: i for i, s in enumerate(present)}))
    enc = dict(
        y=alt.Y("production_mwh:Q", title="Energy (MWh)", stack="zero"),
        color=alt.Color("ship_name:N", title="Ship", scale=theme.ship_scale(present), sort=present,
                        legend=alt.Legend(orient="top")),
        order=alt.Order("ship_order:Q"),
        tooltip=[
            alt.Tooltip("period:T", title="Period start"), alt.Tooltip("ship_name:N", title="Ship"),
            alt.Tooltip("production_mwh:Q", title="Energy (MWh)", format=",.0f"),
            alt.Tooltip("capacity_factor:Q", title="Capacity factor", format=".0%"),
            alt.Tooltip("downtime_days:Q", title="Downtime days"),
        ],
    )
    if freq == "M":
        marks = alt.Chart(d).mark_bar(stroke=None).encode(
            x=alt.X("yearmonth(period):O", title=None, axis=alt.Axis(format="%b %Y", labelAngle=0)), **enc)
        return marks.properties(height=320)
    marks = alt.Chart(d).mark_area(interpolate="monotone", opacity=0.9, line={"strokeWidth": 1}).encode(
        x=alt.X("period:T", title=None), **enc)
    return alt.layer(*_event_layers(events, theme, y_label=True, min_days=14), marks).properties(height=320)


def fleet_lines(
    fleet: pd.DataFrame, metrics: dict[str, str], theme: Theme, y_title: str, fmt: str = ".1%",
    events: pd.DataFrame | None = None, zero: bool = False,
) -> alt.Chart:
    """One or more fleet-level series that share a unit (never a dual axis)."""
    long = fleet.melt(id_vars="period", value_vars=list(metrics), var_name="metric", value_name="value")
    long["metric"] = long["metric"].map(metrics)
    names = list(metrics.values())
    palette = CATEGORICAL[theme.mode]
    line = alt.Chart(long).mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=28)).encode(
        x=alt.X("period:T", title=None),
        y=alt.Y("value:Q", title=y_title, axis=alt.Axis(format=fmt), scale=alt.Scale(zero=zero)),
        color=alt.Color("metric:N", title=None, scale=alt.Scale(domain=names, range=palette[: len(names)]),
                        legend=alt.Legend(orient="top") if len(names) > 1 else None),
        tooltip=[alt.Tooltip("period:T", title="Period"), alt.Tooltip("metric:N", title="Metric"),
                 alt.Tooltip("value:Q", title="Value", format=fmt)],
    )
    return alt.layer(*_event_layers(events, theme, min_days=14), line).properties(height=260)


def ship_small_multiples(
    period: pd.DataFrame, metric: str, title: str, theme: Theme, fmt: str = ".2f",
    events: pd.DataFrame | None = None, columns: int = 2, width: int = 440,
) -> alt.Chart:
    """One panel per ship (independent y), downtime shaded: dips are obvious per ship."""
    present = [s for s in theme.ships if s in set(period["ship_name"])]
    ev = events if events is not None and not events.empty else pd.DataFrame(
        columns=["ship_name", "start", "end", "days", "kind", "cause", "lost_mwh"])
    ev = ev.assign(end_excl=ev["end"] + pd.Timedelta(days=1)) if not ev.empty else ev.assign(end_excl=ev["end"])
    base_line = alt.Chart().mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=20)).encode(
        x=alt.X("period:T", title=None),
        y=alt.Y(f"{metric}:Q", title=title, scale=alt.Scale(zero=False), axis=alt.Axis(format=fmt)),
        color=alt.Color("ship_name:N", scale=theme.ship_scale(present), legend=None),
        tooltip=[alt.Tooltip("ship_name:N", title="Ship"), alt.Tooltip("period:T", title="Period"),
                 alt.Tooltip(f"{metric}:Q", title=title, format=fmt),
                 alt.Tooltip("downtime_days:Q", title="Downtime days")],
    )
    bands = alt.Chart().mark_rect(opacity=0.18).encode(
        x="start:T", x2="end_excl:T",
        fill=alt.Fill("kind:N", scale=theme.status_scale(), legend=None),
        tooltip=[alt.Tooltip("kind:N", title="Event"), alt.Tooltip("cause:N", title="Cause"),
                 alt.Tooltip("start:T"), alt.Tooltip("end:T"), alt.Tooltip("days:Q")],
    )
    data = pd.concat([period.assign(_layer="line"), ev.assign(_layer="band")], ignore_index=True)
    return alt.layer(
        bands.transform_filter("datum._layer == 'band'"),
        base_line.transform_filter("datum._layer == 'line'"),
        data=data,
    ).properties(height=150, width=width).facet(
        facet=alt.Facet("ship_name:N", title=None, sort=present), columns=columns,
    ).resolve_scale(y="independent")


def status_timeline(daily: pd.DataFrame, theme: Theme) -> alt.Chart:
    d = daily[["ship_name", "date", "status", "event_note", "production_mwh", "fuel_consumption_ton"]].copy()
    d["status_label"] = d["status"].map(lambda s: STATUS_LABELS.get(Status(s), s))
    d["date_end"] = d["date"] + pd.Timedelta(days=1)
    present = [s for s in theme.ships if s in set(d["ship_name"])]
    return alt.Chart(d).mark_rect().encode(
        x=alt.X("date:T", title=None), x2="date_end:T",
        y=alt.Y("ship_name:N", title=None, sort=present),
        color=alt.Color("status_label:N", title="Status", scale=theme.status_scale(),
                        legend=alt.Legend(orient="top", columns=4)),
        tooltip=[alt.Tooltip("ship_name:N", title="Ship"), alt.Tooltip("date:T", title="Date"),
                 alt.Tooltip("status_label:N", title="Status"), alt.Tooltip("event_note:N", title="Note"),
                 alt.Tooltip("production_mwh:Q", title="MWh", format=",.1f"),
                 alt.Tooltip("fuel_consumption_ton:Q", title="Fuel (t)", format=",.1f")],
    ).properties(height=alt.Step(24))


def ranking_bar(table: pd.DataFrame, metric: str, title: str, theme: Theme, fmt: str,
                ascending: bool = False, benchmark: float | None = None) -> alt.Chart:
    present = list(table["ship_name"])
    order = table.sort_values(metric, ascending=ascending)["ship_name"].tolist()
    bars = alt.Chart(table).mark_bar(cornerRadiusEnd=3, height=16).encode(
        y=alt.Y("ship_name:N", sort=order, title=None),
        x=alt.X(f"{metric}:Q", title=title, axis=alt.Axis(format=fmt)),
        color=alt.Color("ship_name:N", scale=theme.ship_scale(present), legend=None),
        tooltip=[alt.Tooltip("ship_name:N", title="Ship"), alt.Tooltip(f"{metric}:Q", title=title, format=fmt)],
    )
    labels = bars.mark_text(align="left", dx=4, color=theme.ink2, fontSize=11).encode(
        text=alt.Text(f"{metric}:Q", format=fmt), color=alt.value(theme.ink2))
    layers = [bars, labels]
    if benchmark is not None:
        layers.append(alt.Chart(pd.DataFrame({"b": [benchmark]})).mark_rule(color=theme.ink, strokeWidth=1)
                      .encode(x="b:Q", tooltip=[alt.Tooltip("b:Q", title="Fleet", format=fmt)]))
    return alt.layer(*layers).properties(height=alt.Step(30))


def drilldown(
    ship_daily: pd.DataFrame, baseline: pd.DataFrame, anomalies: pd.DataFrame,
    events: pd.DataFrame, theme: Theme, color: str,
) -> alt.VConcatChart:
    """Daily output (coloured by status) above load-corrected efficiency vs baseline."""
    d = ship_daily.copy()
    d["status_label"] = d["status"].map(lambda s: STATUS_LABELS.get(Status(s), s))
    d["date_end"] = d["date"] + pd.Timedelta(days=1)
    brush = alt.selection_interval(encodings=["x"])
    ev_layers = _event_layers(events, theme, y_label=False)

    prod = alt.Chart(d).mark_rect().encode(
        x=alt.X("date:T", title=None), x2="date_end:T",
        y=alt.Y("production_mwh:Q", title="Energy (MWh/day)"), y2=alt.datum(0),
        color=alt.Color("status_label:N", title="Status", scale=theme.status_scale(),
                        legend=alt.Legend(orient="top", columns=4)),
        tooltip=[alt.Tooltip("date:T"), alt.Tooltip("status_label:N", title="Status"),
                 alt.Tooltip("production_mwh:Q", title="MWh", format=",.1f"),
                 alt.Tooltip("fuel_consumption_ton:Q", title="Fuel (t)", format=",.1f"),
                 alt.Tooltip("capacity_factor:Q", title="Capacity factor", format=".0%"),
                 alt.Tooltip("event_note:N", title="Note")],
    ).add_params(brush)
    top = alt.layer(*ev_layers, prod).properties(height=200, title="Daily output · drag to zoom the chart below")

    xz = alt.X("date:T", title=None, scale=alt.Scale(domain=brush))
    y_title = "Load-corrected efficiency (MWh/t)"
    layers = [*[l.encode(x=xz) for l in ev_layers]]
    if not baseline.empty:
        b = baseline
        layers.append(alt.Chart(b).mark_circle(size=18, opacity=0.35, color=theme.ink2).encode(
            x=xz, y=alt.Y("load_corrected_eff:Q", title=y_title, scale=alt.Scale(zero=False)),
            tooltip=[alt.Tooltip("date:T"), alt.Tooltip("mwh_per_ton:Q", title="Actual MWh/t", format=".2f"),
                     alt.Tooltip("load_corrected_eff:Q", title="Load-corrected", format=".2f")]))
        # Re-index on every calendar day so gaps (downtime, missing data) break the line.
        full = d[["date"]].merge(b[["date", "rolling_eff", "baseline_eff"]], on="date", how="left")
        long = full.melt(id_vars="date", value_vars=["rolling_eff", "baseline_eff"], var_name="series", value_name="v")
        long["series"] = long["series"].map({"rolling_eff": "7-day rolling", "baseline_eff": "60-day baseline"})
        domain = ["7-day rolling", "60-day baseline"]
        layers.append(alt.Chart(long).mark_line(strokeWidth=2, invalid="break-paths-filter-domains").encode(
            x=xz, y=alt.Y("v:Q", title=y_title),
            color=alt.Color("series:N", title=None, scale=alt.Scale(domain=domain, range=[color, theme.ink2]),
                            legend=alt.Legend(orient="top")),
            strokeDash=alt.StrokeDash("series:N", scale=alt.Scale(domain=domain, range=[[1, 0], [5, 3]]), legend=None),
            tooltip=[alt.Tooltip("date:T"), alt.Tooltip("series:N"), alt.Tooltip("v:Q", title="MWh/t", format=".2f")],
        ))
        an = anomalies[anomalies["type"].isin(["Efficiency drift", "Efficiency outlier"])]
        if not an.empty:
            an = an.merge(b[["date", "rolling_eff", "load_corrected_eff"]], on="date", how="left")
            an["y"] = an["rolling_eff"].where(an["type"] == "Efficiency drift", an["load_corrected_eff"])
            layers.append(alt.Chart(an).mark_point(shape="triangle-down", size=60, filled=True,
                                                   color="#dc3c3d").encode(
                x=xz, y="y:Q", tooltip=[alt.Tooltip("date:T"), alt.Tooltip("type:N"), alt.Tooltip("detail:N")]))
    bottom = alt.layer(*layers).properties(
        height=240, title="Efficiency normalised to optimal load vs trailing baseline  (▼ anomaly)")
    return alt.vconcat(top, bottom).resolve_scale(color="independent")


def load_curve(curve: pd.DataFrame, theme: Theme) -> alt.Chart:
    present = [s for s in theme.ships if s in set(curve["ship_name"])]
    return alt.Chart(curve).mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=30)).encode(
        x=alt.X("load_mid:Q", title="Load factor", axis=alt.Axis(format=".0%"), scale=alt.Scale(domain=[0, 1])),
        y=alt.Y("thermal_eff:Q", title="Thermal efficiency", axis=alt.Axis(format=".0%"), scale=alt.Scale(zero=False)),
        color=alt.Color("ship_name:N", title="Ship", scale=theme.ship_scale(present)),
        tooltip=[alt.Tooltip("ship_name:N", title="Ship"), alt.Tooltip("load_mid:Q", title="Load", format=".0%"),
                 alt.Tooltip("thermal_eff:Q", title="Thermal eff.", format=".1%"), alt.Tooltip("days:Q", title="Days")],
    ).properties(height=300)


def anomaly_strip(anomalies: pd.DataFrame, theme: Theme) -> alt.Chart:
    present = [s for s in theme.ships if s in set(anomalies["ship_name"])]
    return alt.Chart(anomalies).mark_tick(thickness=2, size=14).encode(
        x=alt.X("date:T", title=None),
        y=alt.Y("ship_name:N", title=None, sort=present),
        color=alt.Color("severity:N", scale=alt.Scale(domain=list(SEVERITY_COLORS), range=list(SEVERITY_COLORS.values())),
                        legend=alt.Legend(orient="top", title="Severity")),
        tooltip=[alt.Tooltip("ship_name:N", title="Ship"), alt.Tooltip("date:T"), alt.Tooltip("type:N"),
                 alt.Tooltip("detail:N")],
    ).properties(height=alt.Step(24))
