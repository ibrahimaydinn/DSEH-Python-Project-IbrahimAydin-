"""Efficiency, operational and profitability formulas.

    MWh per ton        = production_mwh / fuel_consumption_ton
    SFC (g/kWh)        = 1000 * fuel_t / MWh
    Heat rate (kJ/kWh) = SFC * LHV (MJ/kg)
    Thermal efficiency = 3600 / heat rate
    Capacity factor    = MWh / (capacity_MW * 24 * ship-days)
    Availability       = available ship-days / reported ship-days
    CO2 (t)            = fuel_t * carbon factor of the fuel
    Revenue            = production_mwh * electricity_price
    Fuel cost          = fuel_consumption_ton * fuel_price (per fuel type)
    Profit / Margin    = Revenue - Fuel cost / Profit / Revenue
    Break-even         = fuel cost per MWh (USD/MWh needed to cover fuel)

Totals over several records always use the ratio of sums (total MWh / total
fuel), never the average of daily ratios.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.fleet import FUELS, FuelType, ShipSpec
from src.schema import AVAILABLE, DOWNTIME, Status

_AVAILABLE = [s.value for s in AVAILABLE]
_DOWNTIME = [s.value for s in DOWNTIME]


def safe_div(num, den):
    """Division that yields NaN instead of inf / ZeroDivisionError."""
    if isinstance(den, pd.Series):
        return num / den.where(den != 0)
    if isinstance(num, pd.Series):
        return num / den if den else num * np.nan
    return float(num) / float(den) if den else float("nan")


OPTIMAL_LOAD = 0.85  # load factor at which engines reach peak efficiency
PART_LOAD_PENALTY = 0.5  # efficiency loss coefficient below optimal load


def part_load_curve(load_factor):
    """Relative efficiency vs load (generic OEM-style curve): 1.0 at optimal
    load, lower at part load and slightly lower when pushed past it."""
    lf = np.asarray(load_factor, dtype=float)
    gap = np.clip(OPTIMAL_LOAD - lf, 0.0, None)
    over = np.clip(lf - OPTIMAL_LOAD, 0.0, None)
    return 1.0 - PART_LOAD_PENALTY * gap**2 - 0.3 * over**2


@dataclass(frozen=True)
class Prices:
    electricity_usd_mwh: float = 100.0
    fuel_usd_t: dict[FuelType, float] = field(
        default_factory=lambda: {f: p.default_price_usd_t for f, p in FUELS.items()}
    )

    def fuel(self, fuel_type: FuelType | str) -> float:
        return self.fuel_usd_t[FuelType(fuel_type)]


# --------------------------------------------------------------------------
# Original single-price helpers (kept for the per-day calculator)
# --------------------------------------------------------------------------
def summarize(df: pd.DataFrame, fuel_price: float, elec_price: float) -> dict:
    """Aggregate a set of records into efficiency and profit metrics."""
    mwh = float(df["production_mwh"].sum())
    fuel_t = float(df["fuel_consumption_ton"].sum())
    revenue = mwh * elec_price
    fuel_cost = fuel_t * fuel_price
    profit = revenue - fuel_cost
    mwh_per_ton = safe_div(mwh, fuel_t)
    return {
        "mwh": mwh,
        "fuel_t": fuel_t,
        "mwh_per_ton": mwh_per_ton,
        "revenue": revenue,
        "fuel_cost": fuel_cost,
        "profit": profit,
        "margin": safe_div(profit, revenue) if revenue else 0.0,
        "breakeven": safe_div(fuel_price, mwh_per_ton) if mwh_per_ton == mwh_per_ton else float("nan"),
    }


def add_record_metrics(df: pd.DataFrame, fuel_price: float, elec_price: float) -> pd.DataFrame:
    """Add per-record efficiency and profit columns."""
    out = df.copy()
    out["mwh_per_ton"] = safe_div(out["production_mwh"], out["fuel_consumption_ton"])
    out["revenue"] = out["production_mwh"] * elec_price
    out["fuel_cost"] = out["fuel_consumption_ton"] * fuel_price
    out["profit"] = out["revenue"] - out["fuel_cost"]
    return out


# --------------------------------------------------------------------------
# Fleet analytics
# --------------------------------------------------------------------------
def enrich(daily: pd.DataFrame, registry: dict[str, ShipSpec], prices: Prices) -> pd.DataFrame:
    """Add ship metadata and per-row operational / financial metrics.

    ``daily`` is one row per ship-day (see ``data.daily_by_ship``).
    """
    out = daily.copy()
    spec = out["ship_name"].map(registry)
    out["capacity_mw"] = spec.map(lambda s: s.capacity_mw)
    out["fuel_type"] = spec.map(lambda s: str(s.fuel_type))
    out["site"] = spec.map(lambda s: s.site)
    lhv = out["fuel_type"].map(lambda f: FUELS[FuelType(f)].lhv_mj_per_kg)
    cf = out["fuel_type"].map(lambda f: FUELS[FuelType(f)].co2_t_per_t)
    price = out["fuel_type"].map(prices.fuel)

    mwh, fuel = out["production_mwh"], out["fuel_consumption_ton"]
    out["lhv"] = lhv
    out["mwh_per_ton"] = safe_div(mwh, fuel).where(mwh > 0)
    out["sfc_g_kwh"] = safe_div(1000 * fuel, mwh).where(mwh > 0)
    out["heat_rate_kj_kwh"] = out["sfc_g_kwh"] * lhv
    out["thermal_eff"] = safe_div(3600.0, out["heat_rate_kj_kwh"])
    out["fuel_energy_mwh"] = fuel * lhv / 3.6  # t * MJ/kg = GJ; /3.6 -> MWh
    out["capacity_mwh"] = out["capacity_mw"] * 24.0
    out["capacity_factor"] = safe_div(mwh, out["capacity_mwh"])
    # Efficiency normalised to optimal load: removes the part-load effect so
    # drift detection sees engine condition, not dispatch.
    out["load_corrected_eff"] = out["mwh_per_ton"] / part_load_curve(out["capacity_factor"].clip(0, 1.2))
    out["co2_t"] = fuel * cf
    out["fuel_cost"] = fuel * price
    out["revenue"] = mwh * prices.electricity_usd_mwh
    out["profit"] = out["revenue"] - out["fuel_cost"]
    out["is_available"] = out["status"].isin(_AVAILABLE)
    out["is_downtime"] = out["status"].isin(_DOWNTIME)
    out["is_reported"] = out["status"] != Status.NO_DATA.value
    out["standby_fuel_t"] = fuel.where(out["is_downtime"], 0.0).fillna(0.0)
    return out


SUM_COLS = [
    "production_mwh", "fuel_consumption_ton", "fuel_energy_mwh", "capacity_mwh", "co2_t",
    "fuel_cost", "revenue", "profit", "standby_fuel_t", "operating_hours",
]


def _ratios(agg: pd.DataFrame) -> pd.DataFrame:
    """Recompute ratio metrics from summed columns (ratio of sums)."""
    mwh, fuel = agg["production_mwh"], agg["fuel_consumption_ton"]
    # A period that burned standby fuel but produced nothing has an efficiency
    # of 0 (not NaN): that is exactly the dip the team needs to see.
    agg["mwh_per_ton"] = safe_div(mwh, fuel)
    agg["sfc_g_kwh"] = safe_div(1000 * fuel, mwh).where(mwh > 0)
    agg["thermal_eff"] = safe_div(mwh, agg["fuel_energy_mwh"])
    agg["heat_rate_kj_kwh"] = safe_div(3600.0, agg["thermal_eff"])
    agg["capacity_factor"] = safe_div(mwh, agg["capacity_mwh"])
    agg["availability"] = safe_div(agg["available_days"], agg["reported_days"])
    agg["co2_intensity"] = safe_div(agg["co2_t"], mwh)
    agg["fuel_cost_per_mwh"] = safe_div(agg["fuel_cost"], mwh)
    agg["margin"] = safe_div(agg["profit"], agg["revenue"])
    return agg


def aggregate(enriched: pd.DataFrame, by: list[str] | None = None, freq: str | None = None) -> pd.DataFrame:
    """Aggregate enriched ship-days by optional keys and/or time period.

    Capacity counts only reported ship-days, so missing records do not
    depress the capacity factor.
    """
    df = enriched.assign(
        capacity_mwh=enriched["capacity_mwh"].where(enriched["is_reported"], 0.0),
        available_days=enriched["is_available"].astype(int),
        downtime_days=enriched["is_downtime"].astype(int),
        reported_days=enriched["is_reported"].astype(int),
        ship_days=1,
    )
    keys = list(by or [])
    if freq:
        df["period"] = df["date"].dt.to_period(freq).dt.start_time
        keys.append("period")
    cols = SUM_COLS + ["available_days", "downtime_days", "reported_days", "ship_days"]
    if keys:
        agg = df.groupby(keys, sort=True)[cols].sum(min_count=1).reset_index()
    else:
        agg = df[cols].sum(min_count=1).to_frame().T
    agg[cols] = agg[cols].fillna(0.0)
    return _ratios(agg)


def kpis(enriched: pd.DataFrame) -> dict[str, float]:
    """Headline KPIs for a filtered set of ship-days."""
    if enriched.empty:
        return {}
    row = aggregate(enriched).iloc[0].to_dict()
    row["n_ships"] = enriched["ship_name"].nunique()
    run = enriched[enriched["is_available"]]
    run_agg = aggregate(run).iloc[0] if not run.empty else None
    row["running_mwh_per_ton"] = float(run_agg["mwh_per_ton"]) if run_agg is not None else float("nan")
    return row
