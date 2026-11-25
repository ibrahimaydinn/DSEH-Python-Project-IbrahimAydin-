"""
All the formulas in one place.

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

import numpy as np
import pandas as pd

from karpowership.data import DOWN_STATUSES, NO_DATA, OPERATING, RAMP_UP
from karpowership.fleet import CO2_PER_TON_FUEL, ship_table


def add_daily_metrics(daily, fuel_price=450.0, electricity_price=100.0):
    """
    Add the per-day metrics used by every table and chart.

    Parameters
    ----------
    daily : pandas.DataFrame
        One row per ship and day (see ``data.one_row_per_day``).
    fuel_price : float, optional
        USD per tonne of fuel.
    electricity_price : float, optional
        USD per MWh sold.

    Returns
    -------
    pandas.DataFrame
        The same rows with the ship information and the metric columns added.
    """
    df = daily.merge(ship_table(daily["ship_name"].unique()), on="ship_name", how="left")
    df["max_mwh"] = df["capacity_mw"] * 24

    # No output means no daily efficiency (instead of 0 or a division error).
    df["mwh_per_ton"] = np.where(df["production_mwh"] > 0,
                                 df["production_mwh"] / df["fuel_consumption_ton"], np.nan)
    df["capacity_factor"] = df["production_mwh"] / df["max_mwh"]

    df["fuel_cost"] = df["fuel_consumption_ton"] * fuel_price
    df["revenue"] = df["production_mwh"] * electricity_price
    df["profit"] = df["revenue"] - df["fuel_cost"]
    df["co2_t"] = df["fuel_consumption_ton"] * CO2_PER_TON_FUEL

    df["is_down"] = df["status"].isin(DOWN_STATUSES)
    df["is_available"] = df["status"].isin([OPERATING, RAMP_UP])
    df["has_report"] = df["status"] != NO_DATA
    return df


def summarize(df):
    """
    Totals and ratios for any group of ship-days.

    Parameters
    ----------
    df : pandas.DataFrame
        Rows returned by ``add_daily_metrics`` (any subset).

    Returns
    -------
    dict
    """
    mwh = df["production_mwh"].sum()
    fuel = df["fuel_consumption_ton"].sum()
    max_mwh = df.loc[df["has_report"], "max_mwh"].sum()  # missing reports don't count
    revenue = df["revenue"].sum()

    def ratio(a, b):
        return a / b if b else np.nan

    summary = {
        "production_mwh": mwh,
        "fuel_ton": fuel,
        "mwh_per_ton": ratio(mwh, fuel),
        "capacity_factor": ratio(mwh, max_mwh),
        "availability": ratio(df["is_available"].sum(), df["has_report"].sum()),
        "downtime_days": int(df["is_down"].sum()),
        "co2_per_mwh": ratio(df["co2_t"].sum(), mwh),
        "fuel_cost_per_mwh": ratio(df["fuel_cost"].sum(), mwh),
        "profit": df["profit"].sum(),
        "margin": ratio(df["profit"].sum(), revenue),
    }
    return {key: round(float(value), 4) for key, value in summary.items()}  # plain numbers, easy to read


def summarize_by(df, columns):
    """
    ``summarize`` for each group, e.g. per ship, or per ship and month.

    Parameters
    ----------
    df : pandas.DataFrame
    columns : list of str
        The columns to group by.

    Returns
    -------
    pandas.DataFrame
        One row per group.
    """
    table = df.groupby(columns).apply(lambda group: pd.Series(summarize(group)), include_groups=False)
    return table.reset_index()
