"""
Finding problems in the data: downtime periods, efficiency drops, data issues, savings.

All functions take the daily table from ``calculations.add_daily_metrics``
(one row per ship and day).
"""

import pandas as pd

from karpowership.data import OPERATING
from karpowership.fleet import get_ship

DROP_THRESHOLD = 0.04  # alert when efficiency is more than 4 % below normal


def downtime_events(df, electricity_price):
    """
    One row per downtime period (consecutive down days of the same kind).

    Lost energy = days down x the ship's median daily output in the 30 days before.

    Parameters
    ----------
    df : pandas.DataFrame
        Daily table.
    electricity_price : float
        USD per MWh, used for the lost revenue.

    Returns
    -------
    pandas.DataFrame
        Columns ``ship_name``, ``type``, ``start``, ``end``, ``days``, ``cause``,
        ``standby_fuel_t``, ``lost_mwh``, ``lost_revenue``.
    """
    rows = []
    for ship, days in df.sort_values("date").groupby("ship_name"):
        days = days.reset_index(drop=True)

        # Give every run of identical statuses its own number ("block").
        # shift() moves the column down by one row, so we can compare each day with
        # the day before. True = "status changed"; cumsum() counts the changes so far.
        #   status:  operating operating outage outage outage operating
        #   changed: True      False     True   False  False  True
        #   block:   1         1         2      2      2      3
        # All days of one downtime period therefore share the same block number.
        block = (days["status"] != days["status"].shift()).cumsum()

        for _, event in days[days["is_down"]].groupby(block):
            start, end = event["date"].min(), event["date"].max()

            # The ship's usual output: median of the normal days in the 30 days before.
            before = days[(days["date"] < start) & (days["date"] >= start - pd.Timedelta(days=30))
                          & (days["status"] == OPERATING)]
            normal_output = before["production_mwh"].median() if not before.empty else 0

            # The note looks like "Outage: crankshaft failure (day 1/45)";
            # keep only the text between ":" and "(".
            note = event["event_note"].iloc[0]
            cause = note.split(":")[1].split("(")[0].strip() if ":" in note else ""

            rows.append({
                "ship_name": ship,
                "type": event["status"].iloc[0].capitalize(),  # "outage" -> "Outage"
                "start": start,
                "end": end,
                "days": len(event),
                "cause": cause,
                "standby_fuel_t": round(event["fuel_consumption_ton"].sum(), 1),
                "lost_mwh": round(normal_output * len(event)),
                "lost_revenue": round(normal_output * len(event) * electricity_price),
            })
    columns = ["ship_name", "type", "start", "end", "days", "cause", "standby_fuel_t", "lost_mwh", "lost_revenue"]
    return pd.DataFrame(rows, columns=columns).sort_values("start").reset_index(drop=True)


def efficiency_check(df):
    """
    Compare each ship's recent efficiency with its normal level, day by day.

    recent  = efficiency over the last 7 days (total MWh / total fuel)
    normal  = median daily efficiency over the 60 days before that
    alert   = recent is more than 4 % below normal
    Only normal operating days are used.

    Parameters
    ----------
    df : pandas.DataFrame
        Daily table.

    Returns
    -------
    pandas.DataFrame
        One row per ship and operating day: ``mwh_per_ton``, ``recent``,
        ``normal``, ``change`` (e.g. -0.05 = 5 % below normal) and ``alert``.
    """
    results = []
    for ship, days in df[df["status"] == OPERATING].groupby("ship_name"):
        # With the dates as index, rolling("7D") means "the last 7 calendar days",
        # even when some days are missing.
        days = days.sort_values("date").set_index("date")

        # Efficiency of the last 7 days: total MWh divided by total fuel of those days.
        recent = days["production_mwh"].rolling("7D").sum() / days["fuel_consumption_ton"].rolling("7D").sum()

        # Normal level: median of the last 60 days (at least 10 days of data needed).
        # shift(7, freq="D") moves it 7 days later, so on each day it describes the
        # 60 days BEFORE the recent week. Otherwise a drop would pull "normal" down too.
        normal = days["mwh_per_ton"].rolling("60D", min_periods=10).median().shift(7, freq="D")
        # After the shift some dates no longer match; reindex puts the values back on
        # our dates, and ffill (forward fill) uses the last known value for the gaps.
        normal = normal.reindex(days.index, method="ffill")

        results.append(pd.DataFrame({
            "ship_name": ship,
            "mwh_per_ton": days["mwh_per_ton"],
            "recent": recent,
            "normal": normal,
            "change": recent / normal - 1,  # -0.05 means 5 % below normal
        }).reset_index())

    if not results:
        return pd.DataFrame(columns=["ship_name", "date", "mwh_per_ton", "recent", "normal", "change", "alert"])
    out = pd.concat(results, ignore_index=True)  # stack the tables of all ships
    out["alert"] = out["change"] < -DROP_THRESHOLD
    return out


def efficiency_alerts(check, events, min_days=4):
    """
    Group the alert days into periods, and show whether a downtime followed within 30 days.

    Parameters
    ----------
    check : pandas.DataFrame
        Table returned by ``efficiency_check``.
    events : pandas.DataFrame
        Table returned by ``downtime_events``.
    min_days : int, optional
        Periods shorter than this are ignored (one bad day is not a trend).

    Returns
    -------
    pandas.DataFrame
        One row per alert period.
    """
    alerts = check[check["alert"]].sort_values(["ship_name", "date"])
    rows = []
    for ship, days in alerts.groupby("ship_name"):
        # Same numbering idea as in downtime_events: diff() gives the number of days
        # since the previous alert day; a gap of more than 3 days starts a new period.
        period = (days["date"].diff().dt.days > 3).cumsum()

        for _, p in days.groupby(period):
            if len(p) < min_days:
                continue
            start, end = p["date"].min(), p["date"].max()
            # Did this ship have a downtime that started within 30 days after the alert?
            after = events[(events["ship_name"] == ship) & (events["start"] > end)
                           & (events["start"] <= end + pd.Timedelta(days=30))]
            rows.append({
                "ship_name": ship,
                "from": start,
                "to": end,
                "days": len(p),
                "worst_drop": p["change"].min(),
                "followed_by": after["type"].iloc[0] if not after.empty else "",
                "warning_days_before": (after["start"].iloc[0] - start).days if not after.empty else None,
            })
    return pd.DataFrame(rows, columns=["ship_name", "from", "to", "days", "worst_drop", "followed_by",
                                       "warning_days_before"])


def data_checks(records, daily):
    """
    Simple data-quality checks, one row per check.

    Parameters
    ----------
    records : pandas.DataFrame
        The raw records (before combining same-day records).
    daily : pandas.DataFrame
        The daily table.

    Returns
    -------
    pandas.DataFrame
        Columns ``check`` and ``count``.
    """
    # keep=False marks ALL rows of a duplicate (not only the second one).
    duplicates = records.duplicated(["ship_name", "date"], keep=False)
    duplicate_days = records[duplicates][["ship_name", "date"]].drop_duplicates()
    over_capacity = daily[daily["capacity_factor"] > 1]  # more than the engines can produce
    return pd.DataFrame([
        {"check": "Records with missing production or fuel", "count": int(records["production_mwh"].isna().sum())},
        {"check": "Ship-days with more than one record", "count": len(duplicate_days)},
        {"check": "Days above the ship's maximum output (likely duplicate entry)", "count": len(over_capacity)},
    ])


def fuel_savings(df, fuel_price):
    """
    Extra fuel burned because a ship ran below its design efficiency.

    extra fuel = fuel used - fuel that would have been needed at design efficiency
    (operating days only).

    Parameters
    ----------
    df : pandas.DataFrame
        Daily table.
    fuel_price : float
        USD per tonne.

    Returns
    -------
    pandas.DataFrame
        One row per ship, the most expensive first.
    """
    rows = []
    for ship, days in df[df["status"] == OPERATING].groupby("ship_name"):
        mwh, fuel = days["production_mwh"].sum(), days["fuel_consumption_ton"].sum()
        design = get_ship(ship).design_mwh_per_ton
        extra = max(fuel - mwh / design, 0)  # never negative
        rows.append({
            "ship_name": ship,
            "actual_mwh_per_ton": round(mwh / fuel, 2),
            "design_mwh_per_ton": design,
            "extra_fuel_t": round(extra),
            "extra_cost_usd": round(extra * fuel_price),
        })
    return pd.DataFrame(rows).sort_values("extra_cost_usd", ascending=False)
