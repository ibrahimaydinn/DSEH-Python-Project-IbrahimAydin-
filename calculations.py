"""Efficiency and profitability formulas (same logic as the Quarto analysis).

    MWh per ton   = production_mwh / fuel_consumption_ton
    Revenue       = production_mwh * electricity_price
    Fuel cost     = fuel_consumption_ton * fuel_price
    Profit        = Revenue - Fuel cost
    Margin        = Profit / Revenue
    Break-even    = fuel_price / MWh per ton   (USD/MWh needed to cover fuel)

Totals over several records use the ratio of sums (total MWh / total fuel),
not the average of daily ratios.
"""
import pandas as pd


def summarize(df: pd.DataFrame, fuel_price: float, elec_price: float) -> dict:
    """Aggregate a set of records into efficiency and profit metrics."""
    mwh = df["production_mwh"].sum()
    fuel_t = df["fuel_consumption_ton"].sum()
    revenue = mwh * elec_price
    fuel_cost = fuel_t * fuel_price
    profit = revenue - fuel_cost
    mwh_per_ton = mwh / fuel_t
    return {
        "mwh": mwh,
        "fuel_t": fuel_t,
        "mwh_per_ton": mwh_per_ton,
        "revenue": revenue,
        "fuel_cost": fuel_cost,
        "profit": profit,
        "margin": profit / revenue if revenue else 0.0,
        "breakeven": fuel_price / mwh_per_ton,
    }


def add_record_metrics(df: pd.DataFrame, fuel_price: float, elec_price: float) -> pd.DataFrame:
    """Add per-record efficiency and profit columns."""
    out = df.copy()
    out["mwh_per_ton"] = out["production_mwh"] / out["fuel_consumption_ton"]
    out["revenue"] = out["production_mwh"] * elec_price
    out["fuel_cost"] = out["fuel_consumption_ton"] * fuel_price
    out["profit"] = out["revenue"] - out["fuel_cost"]
    return out
