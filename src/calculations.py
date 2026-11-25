"""All formulas in one place.

Per day
    Efficiency (MWh/t)  = production_mwh / fuel_consumption_ton
    Capacity factor     = production_mwh / (capacity_mw * 24)
    Fuel cost           = fuel_consumption_ton * fuel price
    Revenue             = production_mwh * electricity price
    Profit              = revenue - fuel cost
    CO2 (t)             = fuel_consumption_ton * 3.114

Over a period (always "total divided by total", never an average of ratios)
    Efficiency          = total MWh / total fuel
    Capacity factor     = total MWh / total possible MWh
    Availability        = days able to produce / days with a report
"""
import pandas as pd

from src.data import DOWN_STATUSES, NO_DATA, OPERATING, RAMP_UP
from src.fleet import CO2_PER_TON_FUEL, get_ship


def add_daily_metrics(daily: pd.DataFrame, fuel_price: float, electricity_price: float) -> pd.DataFrame:
    """Add the per-day columns used by every chart and table."""
    df = daily.copy()
    df["capacity_mw"] = df["ship_name"].map(lambda name: get_ship(name).capacity_mw)
    df["max_mwh"] = df["capacity_mw"] * 24

    df["mwh_per_ton"] = df["production_mwh"] / df["fuel_consumption_ton"]
    df.loc[df["production_mwh"] == 0, "mwh_per_ton"] = None  # no output: no daily efficiency
    df["capacity_factor"] = df["production_mwh"] / df["max_mwh"]

    df["fuel_cost"] = df["fuel_consumption_ton"] * fuel_price
    df["revenue"] = df["production_mwh"] * electricity_price
    df["profit"] = df["revenue"] - df["fuel_cost"]
    df["co2_t"] = df["fuel_consumption_ton"] * CO2_PER_TON_FUEL

    df["is_down"] = df["status"].isin(DOWN_STATUSES)
    df["is_available"] = df["status"].isin([OPERATING, RAMP_UP])
    df["has_report"] = df["status"] != NO_DATA
    return df


def summarize(df: pd.DataFrame) -> dict:
    """Totals and ratios for any group of ship-days."""
    mwh = df["production_mwh"].sum()
    fuel = df["fuel_consumption_ton"].sum()
    revenue = df["revenue"].sum()
    profit = df["profit"].sum()
    max_mwh = df.loc[df["has_report"], "max_mwh"].sum()  # missing reports don't count
    days_reported = df["has_report"].sum()

    def ratio(a, b):
        return a / b if b else float("nan")

    return {
        "production_mwh": mwh,
        "fuel_ton": fuel,
        "mwh_per_ton": ratio(mwh, fuel),
        "capacity_factor": ratio(mwh, max_mwh),
        "availability": ratio(df["is_available"].sum(), days_reported),
        "downtime_days": int(df["is_down"].sum()),
        "co2_t": df["co2_t"].sum(),
        "co2_per_mwh": ratio(df["co2_t"].sum(), mwh),
        "fuel_cost_per_mwh": ratio(df["fuel_cost"].sum(), mwh),
        "revenue": revenue,
        "profit": profit,
        "margin": ratio(profit, revenue),
    }


def summarize_by(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """``summarize`` for each group, e.g. per ship or per ship and week."""
    rows = []
    for keys, group in df.groupby(columns):
        keys = keys if isinstance(keys, tuple) else (keys,)
        rows.append({**dict(zip(columns, keys)), **summarize(group)})
    return pd.DataFrame(rows)


def add_period(df: pd.DataFrame, period: str) -> pd.DataFrame:
    """Add a 'period' column with the first day of the week ("W") or month ("M")."""
    df = df.copy()
    df["period"] = df["date"].dt.to_period(period).dt.start_time
    return df
