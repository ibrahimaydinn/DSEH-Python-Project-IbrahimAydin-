"""
Statistics computed with numpy and scipy.

Every function receives the daily table returned by
``calculations.add_daily_metrics`` and returns a small table.
Only normal operating days are used for efficiency statistics, so that
downtime and restarts do not distort the numbers.
"""

import calendar

import numpy as np
import pandas as pd
from scipy import stats

from karpowership.data import OPERATING


def operating_days(daily):
    """Rows where the ship ran normally and reported its numbers."""
    return daily[(daily["status"] == OPERATING) & daily["mwh_per_ton"].notna()]


def efficiency_statistics(daily):
    """
    Descriptive statistics of daily efficiency (MWh per tonne) for each ship.

    Parameters
    ----------
    daily : pandas.DataFrame

    Returns
    -------
    pandas.DataFrame
        One row per ship: days, mean, std, 10th / 50th / 90th percentile and the
        coefficient of variation (std / mean, how stable the ship is).
    """
    rows = []
    for ship, days in operating_days(daily).groupby("ship_name"):
        values = days["mwh_per_ton"].to_numpy()
        p10, p50, p90 = np.percentile(values, [10, 50, 90])
        rows.append({
            "ship_name": ship,
            "days": len(values),
            "mean": values.mean(),
            "std": values.std(ddof=1),
            "p10": p10,
            "median": p50,
            "p90": p90,
            "variation_pct": 100 * values.std(ddof=1) / values.mean(),
        })
    return pd.DataFrame(rows).round(3)


def seasonal_profile(daily):
    """
    Average capacity factor in each calendar month (January ... December).

    Parameters
    ----------
    daily : pandas.DataFrame

    Returns
    -------
    pandas.DataFrame
        Columns ``month_number``, ``month`` and ``capacity_factor``.
    """
    days = daily[daily["has_report"]].copy()
    days["month_number"] = days["date"].dt.month
    profile = days.groupby("month_number")[["production_mwh", "max_mwh"]].sum()
    profile["capacity_factor"] = profile["production_mwh"] / profile["max_mwh"]
    profile["month"] = [calendar.month_abbr[number] for number in profile.index]
    return profile[["month", "capacity_factor"]].reset_index()


def efficiency_trend(daily):
    """
    Is each ship becoming more or less efficient over time? (linear regression)

    A straight line is fitted through the monthly efficiency of each ship with
    ``scipy.stats.linregress``. The slope is converted to "change per year".
    A p-value below 0.05 means the trend is unlikely to be random noise.

    Parameters
    ----------
    daily : pandas.DataFrame

    Returns
    -------
    pandas.DataFrame
        One row per ship: ``change_per_year`` (MWh/t), ``r_squared``, ``p_value``.
    """
    days = operating_days(daily)
    monthly = (days.assign(month=days["date"].dt.to_period("M").dt.start_time)
               .groupby(["ship_name", "month"])[["production_mwh", "fuel_consumption_ton"]].sum()
               .reset_index())
    monthly["mwh_per_ton"] = monthly["production_mwh"] / monthly["fuel_consumption_ton"]

    rows = []
    for ship, months in monthly.groupby("ship_name"):
        if len(months) < 6:
            continue
        years = (months["month"] - months["month"].min()).dt.days / 365.25
        fit = stats.linregress(years, months["mwh_per_ton"])
        rows.append({
            "ship_name": ship,
            "months": len(months),
            "change_per_year": fit.slope,
            "r_squared": fit.rvalue ** 2,
            "p_value": fit.pvalue,
        })
    return pd.DataFrame(rows).round(4)


def before_downtime_test(daily, events, warning_days=21, normal_days=60):
    """
    Did efficiency really drop before each long downtime? (Welch t-test)

    For every downtime of 14 days or more, compare the daily efficiency in the
    ``warning_days`` before it with the ``normal_days`` before that, using
    ``scipy.stats.ttest_ind``. A p-value below 0.05 means the drop is
    statistically significant, i.e. the ship showed a real warning sign.

    Parameters
    ----------
    daily : pandas.DataFrame
    events : pandas.DataFrame
        Table returned by ``alerts.downtime_events``.
    warning_days, normal_days : int, optional

    Returns
    -------
    pandas.DataFrame
        One row per long downtime.
    """
    days = operating_days(daily)
    rows = []
    for _, event in events[events["days"] >= 14].iterrows():
        ship = days[days["ship_name"] == event["ship_name"]]
        warning_start = event["start"] - pd.Timedelta(days=warning_days)
        normal_start = warning_start - pd.Timedelta(days=normal_days)
        warning = ship[(ship["date"] >= warning_start) & (ship["date"] < event["start"])]["mwh_per_ton"]
        normal = ship[(ship["date"] >= normal_start) & (ship["date"] < warning_start)]["mwh_per_ton"]
        if len(warning) < 5 or len(normal) < 5:
            continue
        test = stats.ttest_ind(warning, normal, equal_var=False)
        rows.append({
            "ship_name": event["ship_name"],
            "downtime": f"{event['type']} from {event['start']:%d %b %Y}",
            "normal_mwh_per_ton": normal.mean(),
            "before_mwh_per_ton": warning.mean(),
            "change_pct": 100 * (warning.mean() / normal.mean() - 1),
            "p_value": test.pvalue,
            "significant": bool(test.pvalue < 0.05),
        })
    return pd.DataFrame(rows).round(4)
