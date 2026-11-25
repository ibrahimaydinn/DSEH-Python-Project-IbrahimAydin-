"""Diagnostics on enriched ship-days: anomalies, downtime events, savings potential.

All functions take the output of ``calculations.enrich`` (one row per
ship-day) and are independent of the UI, so they can be tested and reused in
notebooks or reports.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.calculations import Prices
from src.fleet import FUELS, FuelType
from src.schema import STATUS_LABELS, Status

_DOWN = [Status.FORCED_OUTAGE.value, Status.PLANNED_MAINTENANCE.value, Status.DRY_DOCK.value]


@dataclass(frozen=True)
class AnomalySettings:
    baseline_days: int = 60  # trailing window for the "normal" efficiency
    smoothing_days: int = 7  # rolling window for the drift detector
    drift_threshold: float = 0.04  # sustained efficiency drop that counts as drift
    outlier_z: float = 3.0  # robust z-score for single-day outliers
    low_load: float = 0.30  # capacity factor below which an operating day is flagged


def efficiency_baseline(enriched: pd.DataFrame, s: AnomalySettings = AnomalySettings()) -> pd.DataFrame:
    """Per-ship rolling efficiency, trailing baseline and deviation (operating days only).

    Uses load-corrected efficiency so swings caused by dispatch (part load) do
    not register as engine degradation.

    Rolling windows are time-based ("60D") so missing and downtime days do
    not stretch the window. The baseline is lagged by the smoothing window so
    a developing drift does not pull its own reference down.
    """
    out = []
    for _, g in enriched.groupby("ship_name", sort=False):
        g = g.sort_values("date").set_index("date")
        op = g[(g["status"] == Status.OPERATING.value) & g["load_corrected_eff"].notna()]
        if op.empty:
            continue
        lce = op["load_corrected_eff"]
        rolling = lce.rolling(f"{s.smoothing_days}D").mean()
        base = lce.rolling(f"{s.baseline_days}D", min_periods=10).median()
        base = base.shift(s.smoothing_days, freq="D").reindex(op.index, method="ffill")
        resid = lce - lce.rolling("30D", min_periods=10).median()
        mad = resid.abs().rolling("60D", min_periods=10).median() * 1.4826
        out.append(pd.DataFrame({
            "ship_name": op["ship_name"],
            "mwh_per_ton": op["mwh_per_ton"],
            "load_corrected_eff": lce,
            "rolling_eff": rolling,
            "baseline_eff": base,
            "drift": rolling / base - 1,
            "robust_z": resid / mad.replace(0, np.nan),
        }).reset_index())
    if not out:
        return pd.DataFrame(columns=["ship_name", "date", "mwh_per_ton", "load_corrected_eff", "rolling_eff", "baseline_eff", "drift", "robust_z"])
    return pd.concat(out, ignore_index=True)


def detect_anomalies(enriched: pd.DataFrame, s: AnomalySettings = AnomalySettings()) -> pd.DataFrame:
    """Flag ship-days that need an engineer's attention.

    Types: efficiency drift (sustained), efficiency outlier (single day),
    low load, standby burn (fuel with no output), over-capacity (likely
    duplicate entry), missing report.
    """
    base = efficiency_baseline(enriched, s)
    rows: list[pd.DataFrame] = []

    drift = base[base["drift"] < -s.drift_threshold]
    rows.append(drift.assign(
        type="Efficiency drift",
        severity=np.where(drift["drift"] < -2 * s.drift_threshold, "critical", "warning"),
        detail=[f"7-day load-corrected efficiency {d:+.1%} vs 60-day baseline ({b:.2f} MWh/t)"
                for d, b in zip(drift["drift"], drift["baseline_eff"])],
        value=drift["drift"],
    ))
    out = base[base["robust_z"] < -s.outlier_z]
    rows.append(out.assign(
        type="Efficiency outlier", severity="warning",
        detail=[f"{v:.2f} MWh/t, robust z = {z:.1f}" for v, z in zip(out["mwh_per_ton"], out["robust_z"])],
        value=out["robust_z"],
    ))

    e = enriched
    low = e[(e["status"] == Status.OPERATING.value) & (e["capacity_factor"] < s.low_load)]
    rows.append(low.assign(type="Low load", severity="info",
                           detail=[f"Capacity factor {c:.0%}" for c in low["capacity_factor"]],
                           value=low["capacity_factor"]))
    burn = e[e["status"].isin(_DOWN) & (e["fuel_consumption_ton"] > 0)]
    rows.append(burn.assign(type="Standby burn", severity="info",
                            detail=[f"{f:.1f} t burned with no output" for f in burn["fuel_consumption_ton"]],
                            value=burn["fuel_consumption_ton"]))
    over = e[e["capacity_factor"] > 1.02]
    rows.append(over.assign(type="Over capacity", severity="critical",
                            detail=[f"{c:.0%} of nameplate across {n} records: check for duplicate entry"
                                    for c, n in zip(over["capacity_factor"], over["n_records"])],
                            value=over["capacity_factor"]))
    miss = e[e["status"] == Status.NO_DATA.value]
    rows.append(miss.assign(type="Missing report", severity="info", detail="No production/fuel reported", value=np.nan))

    cols = ["ship_name", "date", "type", "severity", "detail", "value"]
    rows = [r[cols] for r in rows if not r.empty]
    if not rows:
        return pd.DataFrame(columns=cols)
    return pd.concat(rows, ignore_index=True).sort_values(["date", "ship_name"]).reset_index(drop=True)


def drift_episodes(anomalies: pd.DataFrame, max_gap_days: int = 3, min_days: int = 4) -> pd.DataFrame:
    """Group consecutive drift days into episodes (start, end, worst drift)."""
    d = anomalies[anomalies["type"] == "Efficiency drift"].sort_values(["ship_name", "date"])
    if d.empty:
        return pd.DataFrame(columns=["ship_name", "start", "end", "days", "worst_drift"])
    new = (d["ship_name"] != d["ship_name"].shift()) | (d["date"].diff().dt.days > max_gap_days)
    d = d.assign(episode=new.cumsum())
    ep = d.groupby("episode").agg(
        ship_name=("ship_name", "first"), start=("date", "min"), end=("date", "max"),
        days=("date", "size"), worst_drift=("value", "min"),
    )
    return ep[ep["days"] >= min_days].reset_index(drop=True)


def downtime_events(
    enriched: pd.DataFrame, prices: Prices | None = None, lookback_days: int = 30
) -> pd.DataFrame:
    """Contiguous downtime runs per ship with impact estimates.

    Lost energy  = days × median output of the ``lookback_days`` before the event.
    Lost revenue = lost energy × electricity price.
    """
    price = (prices or Prices()).electricity_usd_mwh
    events = []
    for ship, g in enriched.sort_values("date").groupby("ship_name", sort=False):
        g = g.reset_index(drop=True)
        is_down = g["status"].isin(_DOWN)
        run_id = (g["status"] != g["status"].shift()).cumsum()
        for _, run in g[is_down].groupby(run_id[is_down]):
            start, end = run["date"].min(), run["date"].max()
            prior = g[(g["date"] < start) & (g["date"] >= start - pd.Timedelta(days=lookback_days))
                      & (g["status"] == Status.OPERATING.value)]
            expected = float(prior["production_mwh"].median()) if not prior.empty else np.nan
            days = len(run)
            note = run["event_note"].iloc[0]
            cause = note.split(":", 1)[1].rsplit("(", 1)[0].strip() if ":" in note else ""
            events.append({
                "ship_name": ship,
                "kind": STATUS_LABELS[Status(run["status"].iloc[0])],
                "status": run["status"].iloc[0],
                "start": start,
                "end": end,
                "days": days,
                "cause": cause,
                "standby_fuel_t": float(run["fuel_consumption_ton"].sum()),
                "standby_fuel_cost": float(run["fuel_cost"].sum()),
                "lost_mwh": expected * days,
                "lost_revenue": expected * days * price,
            })
    df = pd.DataFrame(events)
    if df.empty:
        return pd.DataFrame(columns=["ship_name", "kind", "status", "start", "end", "days", "cause",
                                     "standby_fuel_t", "standby_fuel_cost", "lost_mwh", "lost_revenue"])
    return df.sort_values("start").reset_index(drop=True)


def savings_potential(enriched: pd.DataFrame, prices: Prices, percentile: float = 75.0) -> pd.DataFrame:
    """Fuel that would have been saved had each ship run at its own achievable efficiency.

    Benchmark = the ship's ``percentile``-th daily efficiency on normal operating
    days, i.e. a level it demonstrably reaches. Only operating days count.
    """
    op = enriched[(enriched["status"] == Status.OPERATING.value) & enriched["mwh_per_ton"].notna()]
    rows = []
    for ship, g in op.groupby("ship_name"):
        bench = float(np.percentile(g["mwh_per_ton"], percentile))
        actual = g["production_mwh"].sum() / g["fuel_consumption_ton"].sum()
        ideal_fuel = g["production_mwh"].sum() / bench
        excess = max(g["fuel_consumption_ton"].sum() - ideal_fuel, 0.0)
        fuel = FuelType(g["fuel_type"].iloc[0])
        rows.append({
            "ship_name": ship,
            "fuel_type": str(fuel),
            "actual_mwh_per_ton": actual,
            "benchmark_mwh_per_ton": bench,
            "gap": actual / bench - 1,
            "excess_fuel_t": excess,
            "excess_cost_usd": excess * prices.fuel(fuel),
            "excess_co2_t": excess * FUELS[fuel].co2_t_per_t,
        })
    return pd.DataFrame(rows).sort_values("excess_cost_usd", ascending=False).reset_index(drop=True) if rows else pd.DataFrame()


def load_efficiency_curve(enriched: pd.DataFrame, bins: int = 10) -> pd.DataFrame:
    """Median thermal efficiency by load-factor bin (fuel-neutral), per ship."""
    op = enriched[(enriched["status"] == Status.OPERATING.value) & enriched["thermal_eff"].notna()]
    edges = np.linspace(0, 1.0, bins + 1)
    op = op.assign(load_bin=pd.cut(op["capacity_factor"].clip(upper=0.999), edges))
    curve = op.groupby(["ship_name", "load_bin"], observed=True).agg(
        thermal_eff=("thermal_eff", "median"), days=("date", "size")
    ).reset_index()
    curve["load_mid"] = curve["load_bin"].map(lambda b: b.mid).astype(float)
    return curve.drop(columns="load_bin")


def data_quality(records: pd.DataFrame) -> dict[str, int]:
    """Record-level checks on raw (not aggregated) data."""
    dup = records.duplicated(["ship_name", "date"], keep=False)
    return {
        "records": len(records),
        "missing_values": int(records[["production_mwh", "fuel_consumption_ton"]].isna().any(axis=1).sum()),
        "duplicate_ship_days": int(records[dup].drop_duplicates(["ship_name", "date"]).shape[0]),
        "zero_fuel_with_output": int(((records["fuel_consumption_ton"] == 0) & (records["production_mwh"] > 0)).sum()),
        "negative_values": int((records[["production_mwh", "fuel_consumption_ton"]] < 0).any(axis=1).sum()),
    }
