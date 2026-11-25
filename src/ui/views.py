"""Streamlit tab renderers. Each takes a prepared ``ViewContext``."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd
import streamlit as st

from src import analytics as A
from src.calculations import Prices, add_record_metrics, aggregate, kpis, summarize
from src.data import Dataset, to_excel_bytes, write_excel, SIM_PATH
from src.fleet import FuelType, registry_to_frame
from src.schema import STATUS_LABELS, Status
from src.ui import charts as C


@dataclass
class ViewContext:
    dataset: Dataset
    enriched: pd.DataFrame  # filtered ship-days
    enriched_all: pd.DataFrame  # all ship-days (for prior-period comparison)
    events: pd.DataFrame
    anomalies: pd.DataFrame
    baseline: pd.DataFrame
    prices: Prices
    theme: C.Theme
    freq: str
    freq_label: str
    start: date
    end: date
    settings: A.AnomalySettings
    profiles: dict | None = None


# ---------------------------------------------------------------- helpers
def _fmt(v: float, kind: str) -> str:
    if v is None or v != v:
        return "—"
    return {
        "gwh": f"{v / 1000:,.1f}",
        "kt": f"{v / 1000:,.1f}",
        "pct": f"{v:.1%}",
        "mwhpt": f"{v:.2f}",
        "sfc": f"{v:,.0f}",
        "hr": f"{v:,.0f}",
        "usd": f"${v:,.0f}",
        "usdm": f"${v / 1e6:,.2f}M",
        "usd_mwh": f"${v:,.1f}",
        "co2i": f"{v:.3f}",
        "days": f"{v:,.0f}",
    }[kind]


def _delta(cur: dict, prev: dict | None, key: str, kind: str) -> str | None:
    if not prev or key not in prev or prev[key] != prev[key] or cur.get(key) != cur.get(key):
        return None
    d = cur[key] - prev[key]
    if kind == "pct":
        return f"{d * 100:+.1f} pp"
    if kind in ("gwh", "kt", "usdm"):
        return f"{d / prev[key]:+.1%}" if prev[key] else None
    if kind == "mwhpt":
        return f"{d:+.2f}"
    if kind == "days":
        return f"{d:+.0f}"
    return f"{d:+.1f}" if kind != "co2i" else f"{d:+.3f}"


def _metric(col, label: str, cur: dict, prev: dict | None, key: str, kind: str,
            higher_is_better: bool = True, help: str | None = None) -> None:
    col.metric(label, _fmt(cur.get(key, float("nan")), kind), delta=_delta(cur, prev, key, kind),
               delta_color="normal" if higher_is_better else "inverse", help=help, border=True)


def _prior_window(ctx: ViewContext) -> pd.DataFrame:
    span = pd.Timestamp(ctx.end) - pd.Timestamp(ctx.start)
    p_end = pd.Timestamp(ctx.start) - pd.Timedelta(days=1)
    p_start = p_end - span
    ships = ctx.enriched["ship_name"].unique()
    e = ctx.enriched_all
    return e[(e["date"] >= p_start) & (e["date"] <= p_end) & e["ship_name"].isin(ships)]


def _complete_periods(df: pd.DataFrame, ctx: ViewContext) -> pd.DataFrame:
    """Drop periods only partly inside the selected range (avoids a fake
    drop-off at the edges of weekly/monthly charts)."""
    if ctx.freq == "D" or df.empty:
        return df
    starts = df["period"]
    ends = (starts.dt.to_period(ctx.freq) + 1).dt.start_time - pd.Timedelta(days=1)
    keep = (starts >= pd.Timestamp(ctx.start)) & (ends <= pd.Timestamp(ctx.end))
    return df[keep] if keep.any() else df


def _events_in_scope(ctx: ViewContext) -> pd.DataFrame:
    ev = ctx.events
    if ev.empty:
        return ev
    ships = set(ctx.enriched["ship_name"])
    return ev[ev["ship_name"].isin(ships) & (ev["end"] >= pd.Timestamp(ctx.start)) & (ev["start"] <= pd.Timestamp(ctx.end))]


def _early_warnings(ctx: ViewContext) -> pd.DataFrame:
    """Link drift episodes to a downtime event that follows within 30 days."""
    eps = A.drift_episodes(ctx.anomalies)
    ev = ctx.events
    rows = []
    for _, e in eps.iterrows():
        nxt = ev[(ev["ship_name"] == e["ship_name"]) & (ev["start"] > e["end"]) &
                 (ev["start"] <= e["end"] + pd.Timedelta(days=30))]
        rows.append({**e.to_dict(),
                     "followed_by": nxt.iloc[0]["kind"] if not nxt.empty else "",
                     "lead_days": int((nxt.iloc[0]["start"] - e["start"]).days) if not nxt.empty else None})
    out = pd.DataFrame(rows)
    if not out.empty:
        out["lead_days"] = out["lead_days"].astype("Int64")
    return out


# ---------------------------------------------------------------- tabs
def fleet_overview(ctx: ViewContext) -> None:
    e = ctx.enriched
    if e.empty:
        st.info("No data in the selected range.")
        return
    cur = kpis(e)
    prior = _prior_window(ctx)
    prev = kpis(prior) if len(prior) >= 0.5 * len(e) else None

    # Callouts for major downtime events in scope.
    ev = _events_in_scope(ctx)
    warn = _early_warnings(ctx)
    for _, r in ev[ev["days"] >= 14].iterrows():
        precursor = warn[(warn["ship_name"] == r["ship_name"]) & (warn["followed_by"] == r["kind"])] if not warn.empty else warn
        pre_txt = ""
        if not precursor.empty:
            p = precursor.iloc[-1]
            pre_txt = (f" **Early warning:** efficiency drift from {p['start']:%d %b} "
                       f"(worst {p['worst_drift']:+.1%}), {int(p['lead_days'])} days before the outage.")
        msg = (f"**{r['ship_name']} · {r['kind']}** {r['start']:%d %b %Y} → {r['end']:%d %b %Y} "
               f"({r['days']} days){': ' + r['cause'] if r['cause'] else ''}. "
               f"Est. **{r['lost_mwh']:,.0f} MWh** not generated (≈ {_fmt(r['lost_revenue'], 'usdm')} revenue), "
               f"{r['standby_fuel_t']:,.0f} t standby fuel burned.{pre_txt}")
        (st.error if r["status"] == Status.FORCED_OUTAGE.value else st.warning)(msg, icon="⚠️")

    st.caption(
        f"{cur['n_ships']:.0f} ships · {ctx.start:%d %b %Y} – {ctx.end:%d %b %Y}"
        + (" · deltas vs the preceding period of equal length" if prev else "")
    )
    c = st.columns(5)
    _metric(c[0], "Energy produced (GWh)", cur, prev, "production_mwh", "gwh")
    _metric(c[1], "Fuel consumed (kt)", cur, prev, "fuel_consumption_ton", "kt", higher_is_better=False)
    _metric(c[2], "Fleet thermal efficiency", cur, prev, "thermal_eff", "pct",
            help="Electrical output / fuel energy (LHV). Fuel-neutral, so HFO and LNG ships compare fairly.")
    _metric(c[3], "Fleet MWh per tonne", cur, prev, "mwh_per_ton", "mwhpt",
            help="Total MWh / total fuel tonnes, including standby burn on downtime days.")
    _metric(c[4], "Heat rate (kJ/kWh)", cur, prev, "heat_rate_kj_kwh", "hr", higher_is_better=False)
    c = st.columns(5)
    _metric(c[0], "Capacity factor", cur, prev, "capacity_factor", "pct",
            help="Energy / (installed MW × 24 h × reported ship-days).")
    _metric(c[1], "Availability", cur, prev, "availability", "pct",
            help="Share of reported ship-days the ship was able to generate.")
    _metric(c[2], "Downtime ship-days", cur, prev, "downtime_days", "days", higher_is_better=False)
    _metric(c[3], "CO₂ intensity (t/MWh)", cur, prev, "co2_intensity", "co2i", higher_is_better=False)
    _metric(c[4], "Fuel cost (USD/MWh)", cur, prev, "fuel_cost_per_mwh", "usd_mwh", higher_is_better=False,
            help="Also the break-even electricity price for fuel cost.")

    period = _complete_periods(aggregate(e, by=["ship_name"], freq=ctx.freq), ctx)
    fleet = _complete_periods(aggregate(e, freq=ctx.freq), ctx)
    st.subheader(f"{ctx.freq_label} energy by ship")
    st.altair_chart(C.energy_by_ship(period, ctx.theme, ev, ctx.freq), width="stretch")

    l, r = st.columns(2)
    with l:
        st.markdown(f"**Fleet efficiency ({ctx.freq_label.lower()})**")
        st.altair_chart(C.fleet_lines(fleet, {"thermal_eff": "Thermal efficiency"}, ctx.theme,
                                      "Thermal efficiency", ".1%", ev), width="stretch")
        st.caption("Includes standby fuel on downtime days: an outage pulls it down even though "
                   "the other ships keep running normally.")
    with r:
        st.markdown(f"**Capacity factor and availability ({ctx.freq_label.lower()})**")
        st.altair_chart(C.fleet_lines(fleet, {"capacity_factor": "Capacity factor", "availability": "Availability"},
                                      ctx.theme, "Share", ".0%", ev), width="stretch")
        st.caption("Where a single-ship outage shows most clearly at fleet level.")

    st.subheader("Fleet status timeline")
    st.altair_chart(C.status_timeline(e, ctx.theme), width="stretch")


def ship_comparison(ctx: ViewContext) -> None:
    e = ctx.enriched
    if e.empty:
        st.info("No data in the selected range.")
        return
    table = aggregate(e, by=["ship_name"])
    meta = registry_to_frame(ctx.dataset.registry).rename(columns={"name": "ship_name"})
    table = table.merge(meta[["ship_name", "capacity_mw", "fuel_type", "site"]], on="ship_name", how="left")
    order = {s: i for i, s in enumerate(ctx.theme.ships)}
    table = table.sort_values("ship_name", key=lambda s: s.map(order)).reset_index(drop=True)
    fleet = kpis(e)

    st.dataframe(
        table[["ship_name", "site", "fuel_type", "capacity_mw", "production_mwh", "fuel_consumption_ton",
               "mwh_per_ton", "thermal_eff", "sfc_g_kwh", "capacity_factor", "availability", "downtime_days",
               "co2_intensity", "fuel_cost_per_mwh", "margin"]],
        hide_index=True, width="stretch",
        column_config={
            "ship_name": "Ship", "site": "Site", "fuel_type": "Fuel",
            "capacity_mw": st.column_config.NumberColumn("MW", format="%.0f"),
            "production_mwh": st.column_config.NumberColumn("Energy (MWh)", format="%,.0f"),
            "fuel_consumption_ton": st.column_config.NumberColumn("Fuel (t)", format="%,.0f"),
            "mwh_per_ton": st.column_config.NumberColumn("MWh/t", format="%.2f"),
            "thermal_eff": st.column_config.ProgressColumn("Thermal eff.", format="percent", min_value=0.35, max_value=0.50),
            "sfc_g_kwh": st.column_config.NumberColumn("SFC (g/kWh)", format="%.0f"),
            "capacity_factor": st.column_config.ProgressColumn("Capacity factor", format="percent", min_value=0, max_value=1),
            "availability": st.column_config.ProgressColumn("Availability", format="percent", min_value=0, max_value=1),
            "downtime_days": st.column_config.NumberColumn("Downtime d", format="%.0f"),
            "co2_intensity": st.column_config.NumberColumn("tCO₂/MWh", format="%.3f"),
            "fuel_cost_per_mwh": st.column_config.NumberColumn("Fuel $/MWh", format="$%.1f"),
            "margin": st.column_config.NumberColumn("Fuel margin", format="percent"),
        },
    )

    metrics = {
        "Thermal efficiency": ("thermal_eff", ".1%", False),
        "Capacity factor": ("capacity_factor", ".0%", False),
        "Availability": ("availability", ".0%", False),
        "Fuel cost per MWh": ("fuel_cost_per_mwh", "$.1f", True),
        "CO₂ intensity (t/MWh)": ("co2_intensity", ".3f", True),
        "MWh per tonne": ("mwh_per_ton", ".2f", False),
    }
    l, r = st.columns([1, 1])
    with l:
        choice = st.selectbox("Rank ships by", list(metrics), key="rank_metric")
        key, fmt, asc = metrics[choice]
        st.altair_chart(C.ranking_bar(table, key, choice, ctx.theme, fmt, ascending=asc, benchmark=fleet.get(key)),
                        width="stretch")
        st.caption("Vertical rule = fleet value (ratio of totals).")
    with r:
        st.markdown("**Efficiency vs load**")
        curve = A.load_efficiency_curve(e)
        if not curve.empty:
            st.altair_chart(C.load_curve(curve, ctx.theme), width="stretch")
            op = e[(e["status"] == Status.OPERATING.value)]
            low = op[op["capacity_factor"] < 0.5]
            st.caption(f"Engines run most efficiently at 75–95 % load. {len(low)} operating ship-days "
                       f"({len(low) / max(len(op), 1):.0%}) ran below 50 % load: a dispatch/engine-count "
                       "optimisation candidate.")

    st.subheader(f"{ctx.freq_label} trend per ship")
    sm = {"MWh per tonne": ("mwh_per_ton", ".2f"), "Thermal efficiency": ("thermal_eff", ".1%"),
          "Capacity factor": ("capacity_factor", ".0%"), "Energy (MWh)": ("production_mwh", ",.0f")}
    choice = st.radio("Metric", list(sm), horizontal=True, key="sm_metric")
    key, fmt = sm[choice]
    period = _complete_periods(aggregate(e, by=["ship_name"], freq=ctx.freq), ctx)
    st.altair_chart(C.ship_small_multiples(period, key, choice, ctx.theme, fmt, _events_in_scope(ctx)),
                    width="content")
    st.caption("Shaded bands: downtime (red = forced outage, blue = planned maintenance, violet = dry-dock). "
               "Periods with only standby burn show 0 MWh/t.")


def ship_drilldown(ctx: ViewContext) -> None:
    e = ctx.enriched
    ships = [s for s in ctx.theme.ships if s in set(e["ship_name"])]
    if not ships:
        st.info("No data in the selected range.")
        return
    default = ships.index("Rauf Bey") if "Rauf Bey" in ships else 0
    ship = st.selectbox("Ship", ships, index=default, key="drill_ship")
    sd = e[e["ship_name"] == ship].sort_values("date")
    spec = ctx.dataset.registry[ship]
    k = kpis(sd)
    st.caption(f"{spec.site} · {spec.capacity_mw:.0f} MW · {spec.fuel_type} fuel"
               + (f" · commissioned {spec.commissioned:%d %b %Y}" if spec.commissioned else ""))
    c = st.columns(6)
    _metric(c[0], "Energy (GWh)", k, None, "production_mwh", "gwh")
    _metric(c[1], "MWh per tonne", k, None, "mwh_per_ton", "mwhpt")
    _metric(c[2], "Thermal efficiency", k, None, "thermal_eff", "pct")
    _metric(c[3], "Capacity factor", k, None, "capacity_factor", "pct")
    _metric(c[4], "Availability", k, None, "availability", "pct")
    _metric(c[5], "Fuel margin", k, None, "margin", "pct")

    base = ctx.baseline[ctx.baseline["ship_name"] == ship]
    an = ctx.anomalies[ctx.anomalies["ship_name"] == ship]
    ev = ctx.events[ctx.events["ship_name"] == ship]
    st.altair_chart(C.drilldown(sd, base, an, ev, ctx.theme, ctx.theme.ship_colors.get(ship, "#257de0")),
                    width="stretch")

    l, r = st.columns(2)
    with l:
        st.markdown("**Downtime events**")
        if ev.empty:
            st.caption("None in range.")
        else:
            st.dataframe(ev[["kind", "start", "end", "days", "cause", "standby_fuel_t", "lost_mwh"]],
                         hide_index=True, width="stretch",
                         column_config={"start": st.column_config.DateColumn(format="DD MMM YYYY"),
                                        "end": st.column_config.DateColumn(format="DD MMM YYYY"),
                                        "standby_fuel_t": st.column_config.NumberColumn("Standby fuel (t)", format="%.1f"),
                                        "lost_mwh": st.column_config.NumberColumn("Est. lost MWh", format="%,.0f")})
    with r:
        st.markdown("**Efficiency anomalies**")
        eff_an = an[an["type"].isin(["Efficiency drift", "Efficiency outlier", "Over capacity"])]
        if eff_an.empty:
            st.caption("None in range.")
        else:
            st.dataframe(eff_an[["date", "type", "severity", "detail"]], hide_index=True, width="stretch",
                         column_config={"date": st.column_config.DateColumn(format="DD MMM YYYY")}, height=220)

    # Original per-day calculator, kept for single-day questions.
    with st.expander("Single-day calculator", expanded=False):
        dates = sd["date"].dt.date
        day = st.date_input("Date", value=dates.max(), min_value=dates.min(), max_value=dates.max(), key="calc_day")
        recs = ctx.dataset.records
        day_df = recs[(recs["ship_name"] == ship) & (recs["date"].dt.date == day)].dropna(
            subset=["production_mwh", "fuel_consumption_ton"])
        row = sd[sd["date"].dt.date == day]
        if not row.empty and row.iloc[0]["status"] != Status.OPERATING.value:
            st.info(f"Status: **{STATUS_LABELS[Status(row.iloc[0]['status'])]}**. {row.iloc[0]['event_note']}")
        if day_df.empty:
            st.warning("No valid record for this ship on this date.")
        else:
            fuel_price = ctx.prices.fuel(spec.fuel_type)
            d = summarize(day_df, fuel_price, ctx.prices.electricity_usd_mwh)
            p = summarize(sd.dropna(subset=["production_mwh"]), fuel_price, ctx.prices.electricity_usd_mwh)
            c1, c2, c3 = st.columns(3)
            c1.metric("Efficiency (MWh/t)", f"{d['mwh_per_ton']:.2f}" if d["mwh_per_ton"] == d["mwh_per_ton"] else "—",
                      delta=f"{d['mwh_per_ton'] - p['mwh_per_ton']:+.2f} vs period" if d["mwh"] > 0 else None)
            c2.metric("Electricity produced", f"{d['mwh']:,.1f} MWh")
            c3.metric("Fuel used", f"{d['fuel_t']:,.1f} t")
            c4, c5, c6 = st.columns(3)
            c4.metric("Revenue", f"${d['revenue']:,.0f}")
            c5.metric("Fuel cost", f"${d['fuel_cost']:,.0f}")
            c6.metric("Profit", f"${d['profit']:,.0f}", delta=f"{d['margin']:.1%} margin" if d["revenue"] else None)
            if d["mwh"] > 0:
                st.write(f"**Break-even electricity price:** ${d['breakeven']:,.0f}/MWh")
            if len(day_df) > 1:
                st.info(f"{len(day_df)} records on this date; figures combine them.")
                st.dataframe(add_record_metrics(day_df, fuel_price, ctx.prices.electricity_usd_mwh)[
                    ["production_mwh", "fuel_consumption_ton", "mwh_per_ton", "profit"]].round(2), hide_index=True)


def downtime_and_anomalies(ctx: ViewContext) -> None:
    ev = _events_in_scope(ctx)
    st.subheader("Downtime events")
    if ev.empty:
        st.caption("No downtime in range.")
    else:
        c = st.columns(4)
        c[0].metric("Events", f"{len(ev)}", border=True)
        c[1].metric("Ship-days down", f"{ev['days'].sum():,.0f}", border=True)
        c[2].metric("Est. energy not generated", f"{ev['lost_mwh'].sum() / 1000:,.1f} GWh", border=True)
        c[3].metric("Est. revenue forgone", _fmt(ev["lost_revenue"].sum(), "usdm"), border=True)
        st.dataframe(
            ev[["ship_name", "kind", "start", "end", "days", "cause", "standby_fuel_t", "standby_fuel_cost",
                "lost_mwh", "lost_revenue"]],
            hide_index=True, width="stretch",
            column_config={
                "ship_name": "Ship", "kind": "Type",
                "start": st.column_config.DateColumn("Start", format="DD MMM YYYY"),
                "end": st.column_config.DateColumn("End", format="DD MMM YYYY"),
                "standby_fuel_t": st.column_config.NumberColumn("Standby fuel (t)", format="%.1f"),
                "standby_fuel_cost": st.column_config.NumberColumn("Standby cost", format="$%,.0f"),
                "lost_mwh": st.column_config.NumberColumn("Est. lost MWh", format="%,.0f"),
                "lost_revenue": st.column_config.NumberColumn("Est. lost revenue", format="$%,.0f"),
            },
        )
        st.caption("Lost energy = downtime days × median daily output in the 30 operating days before the event.")

    st.subheader("Early-warning: efficiency drift episodes")
    warn = _early_warnings(ctx)
    if warn.empty:
        st.caption("No sustained drift detected.")
    else:
        warn = warn[warn["ship_name"].isin(set(ctx.enriched["ship_name"]))]
        st.dataframe(warn, hide_index=True, width="stretch", column_config={
            "ship_name": "Ship",
            "start": st.column_config.DateColumn("From", format="DD MMM YYYY"),
            "end": st.column_config.DateColumn("To", format="DD MMM YYYY"),
            "days": "Days flagged",
            "worst_drift": st.column_config.NumberColumn("Worst drift", format="percent"),
            "followed_by": "Followed by (≤30 d)",
            "lead_days": "Lead time (d)",
        })
        st.caption(f"Drift = 7-day load-corrected efficiency more than {ctx.settings.drift_threshold:.0%} "
                   f"below the ship's trailing {ctx.settings.baseline_days}-day baseline.")

    st.subheader("Anomaly log")
    an = ctx.anomalies[ctx.anomalies["ship_name"].isin(set(ctx.enriched["ship_name"]))
                       & (ctx.anomalies["date"] >= pd.Timestamp(ctx.start))
                       & (ctx.anomalies["date"] <= pd.Timestamp(ctx.end))]
    types = sorted(an["type"].unique())
    default = [t for t in types if t not in ("Standby burn", "Missing report")]
    pick = st.multiselect("Types", types, default=default, key="an_types")
    an = an[an["type"].isin(pick)]
    if an.empty:
        st.caption("Nothing to show.")
    else:
        st.altair_chart(C.anomaly_strip(an, ctx.theme), width="stretch")
        st.dataframe(an, hide_index=True, width="stretch", height=260, column_config={
            "date": st.column_config.DateColumn(format="DD MMM YYYY"), "value": None})

    st.subheader("Fuel-savings potential")
    pct = st.slider("Benchmark: each ship's own efficiency percentile", 50, 95, 75, 5, key="bench_pct",
                    help="Fuel saved if every operating day had run at the ship's own P-th best efficiency.")
    sav = A.savings_potential(ctx.enriched, ctx.prices, pct)
    if not sav.empty:
        c = st.columns(3)
        c[0].metric("Excess fuel", f"{sav['excess_fuel_t'].sum():,.0f} t", border=True)
        c[1].metric("Excess fuel cost", _fmt(sav["excess_cost_usd"].sum(), "usdm"), border=True)
        c[2].metric("Avoidable CO₂", f"{sav['excess_co2_t'].sum():,.0f} t", border=True)
        st.dataframe(sav, hide_index=True, width="stretch", column_config={
            "ship_name": "Ship", "fuel_type": "Fuel",
            "actual_mwh_per_ton": st.column_config.NumberColumn("Actual MWh/t", format="%.2f"),
            "benchmark_mwh_per_ton": st.column_config.NumberColumn(f"P{pct} MWh/t", format="%.2f"),
            "gap": st.column_config.NumberColumn("Gap", format="percent"),
            "excess_fuel_t": st.column_config.NumberColumn("Excess fuel (t)", format="%,.0f"),
            "excess_cost_usd": st.column_config.NumberColumn("Excess cost", format="$%,.0f"),
            "excess_co2_t": st.column_config.NumberColumn("Excess CO₂ (t)", format="%,.0f"),
        })


def data_and_simulation(ctx: ViewContext, add_record_cb) -> None:
    recs = ctx.dataset.records
    q = A.data_quality(recs)
    st.subheader("Data quality")
    c = st.columns(4)
    c[0].metric("Records", f"{q['records']:,}", border=True)
    c[1].metric("Missing values", f"{q['missing_values']:,}", border=True)
    c[2].metric("Duplicate ship-days", f"{q['duplicate_ship_days']:,}", border=True,
                help="Several records on one ship-day are summed. If the sum exceeds nameplate capacity "
                     "it is flagged 'Over capacity' in the anomaly log.")
    c[3].metric("Zero fuel with output", f"{q['zero_fuel_with_output']:,}", border=True)

    st.subheader("Add a record")
    with st.form("add_record", clear_on_submit=True, border=True):
        ships = list(ctx.dataset.registry)
        a, b, c3 = st.columns(3)
        ship = a.selectbox("Ship", ships + ["➕ New ship…"])
        new_name = a.text_input("New ship name", help="Used only if '➕ New ship…' is selected.")
        day = b.date_input("Date", value=ctx.end)
        status = b.selectbox("Status", [s.value for s in Status], format_func=lambda s: STATUS_LABELS[Status(s)])
        mwh = c3.number_input("Production (MWh)", min_value=0.0, value=350.0, step=10.0)
        fuel = c3.number_input("Fuel (t)", min_value=0.0, value=70.0, step=1.0)
        note = st.text_input("Event note")
        new_cap = st.number_input("Capacity of new ship (MW)", min_value=1.0, value=25.0,
                                  help="Only for a new ship.")
        new_fuel = st.selectbox("Fuel type of new ship", [f.value for f in FuelType])
        if st.form_submit_button("Add record", type="primary"):
            name = new_name.strip() if ship.startswith("➕") else ship
            if not name:
                st.error("Enter a ship name.")
            else:
                add_record_cb({
                    "ship_name": name, "date": pd.Timestamp(day), "production_mwh": mwh,
                    "fuel_consumption_ton": fuel, "status": status,
                    "operating_hours": 24.0 if status == Status.OPERATING.value else 0.0,
                    "event_note": note, "source": "manual",
                }, new_cap, new_fuel)
                st.session_state["flash"] = f"Added {name} · {day}. Records added this session appear in every view."
                st.rerun()

    st.subheader("Export")
    a, b, c3 = st.columns(3)
    a.download_button("Download Excel (daily + ships)", to_excel_bytes(recs, ctx.dataset.registry),
                      "powership_data.xlsx", width="stretch")
    out = recs.copy()
    out["date"] = out["date"].dt.date
    b.download_button("Download CSV", out.to_csv(index=False).encode("utf-8"), "powership_data.csv",
                      width="stretch")
    if c3.button(f"Save to data/{SIM_PATH.name}", width="stretch"):
        write_excel(SIM_PATH, recs, ctx.dataset.registry)
        st.success(f"Saved {len(recs):,} records to {SIM_PATH.relative_to(SIM_PATH.parent.parent)}")

    st.subheader("Records")
    view = recs[(recs["date"] >= pd.Timestamp(ctx.start)) & (recs["date"] <= pd.Timestamp(ctx.end))
                & recs["ship_name"].isin(set(ctx.enriched["ship_name"]))]
    st.dataframe(view, hide_index=True, width="stretch", height=320,
                 column_config={"date": st.column_config.DateColumn(format="YYYY-MM-DD")})

    l, r = st.columns(2)
    with l:
        st.markdown("**Ship registry**")
        st.dataframe(registry_to_frame(ctx.dataset.registry), hide_index=True, width="stretch")
    with r:
        if ctx.profiles:
            st.markdown("**Simulation profiles** (original ships calibrated on the Excel data)")
            prof = pd.DataFrame([{
                "ship": p.name, "base load": p.base_load_factor, "load σ": p.load_volatility,
                "peak MWh/t": p.peak_mwh_per_ton, "eff σ": p.efficiency_noise,
                "season amp.": p.seasonal_amplitude, "peak month": p.peak_month,
                "trip rate": p.trip_rate, "fouling/30d": p.fouling_per_30d,
            } for p in ctx.profiles.values()])
            st.dataframe(prof, hide_index=True, width="stretch")
