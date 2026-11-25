"""Finding problems in the data: downtime, efficiency drops, data issues, savings.

All functions take the daily table from ``calculations.add_daily_metrics``.
"""
import pandas as pd

from karpowership.data import DOWN_STATUSES, OPERATING
from karpowership.fleet import get_ship

DROP_THRESHOLD = 0.04  # alert when efficiency is 4 % below normal


def downtime_events(df: pd.DataFrame, electricity_price: float) -> pd.DataFrame:
    """One row per downtime period (consecutive down days of the same kind).

    Lost energy = days down x the ship's median daily output in the 30 days before.
    """
    rows = []
    for ship, days in df.sort_values("date").groupby("ship_name"):
        days = days.reset_index(drop=True)
        # A new block starts every time the status changes.
        block = (days["status"] != days["status"].shift()).cumsum()
        for _, event in days[days["is_down"]].groupby(block):
            start, end = event["date"].min(), event["date"].max()
            before = days[(days["date"] < start) & (days["date"] >= start - pd.Timedelta(days=30))
                          & (days["status"] == OPERATING)]
            normal_output = before["production_mwh"].median() if not before.empty else 0
            note = event["event_note"].iloc[0]
            rows.append({
                "ship_name": ship,
                "type": event["status"].iloc[0].capitalize(),
                "start": start,
                "end": end,
                "days": len(event),
                "cause": note.split(":")[1].split("(")[0].strip() if ":" in note else "",
                "standby_fuel_t": round(event["fuel_consumption_ton"].sum(), 1),
                "lost_mwh": round(normal_output * len(event)),
                "lost_revenue": round(normal_output * len(event) * electricity_price),
            })
    columns = ["ship_name", "type", "start", "end", "days", "cause", "standby_fuel_t", "lost_mwh", "lost_revenue"]
    return pd.DataFrame(rows, columns=columns).sort_values("start").reset_index(drop=True)


def efficiency_check(df: pd.DataFrame) -> pd.DataFrame:
    """Compare each ship's recent efficiency with its normal level.

    recent  = efficiency over the last 7 days (total MWh / total fuel)
    normal  = median daily efficiency over the 60 days before that
    alert   = recent is more than 4 % below normal
    Only normal operating days are used.
    """
    results = []
    for ship, days in df[df["status"] == OPERATING].groupby("ship_name"):
        days = days.sort_values("date").set_index("date")
        recent = days["production_mwh"].rolling("7D").sum() / days["fuel_consumption_ton"].rolling("7D").sum()
        normal = days["mwh_per_ton"].rolling("60D", min_periods=10).median().shift(7, freq="D")
        normal = normal.reindex(days.index, method="ffill")
        results.append(pd.DataFrame({
            "ship_name": ship,
            "mwh_per_ton": days["mwh_per_ton"],
            "recent": recent,
            "normal": normal,
            "change": recent / normal - 1,
        }).reset_index())
    if not results:
        return pd.DataFrame(columns=["ship_name", "date", "mwh_per_ton", "recent", "normal", "change", "alert"])
    out = pd.concat(results, ignore_index=True)
    out["alert"] = out["change"] < -DROP_THRESHOLD
    return out


def efficiency_alerts(check: pd.DataFrame, events: pd.DataFrame, min_days: int = 4) -> pd.DataFrame:
    """Group alert days into periods, and show whether a downtime followed within 30 days."""
    alerts = check[check["alert"]].sort_values(["ship_name", "date"])
    rows = []
    for ship, days in alerts.groupby("ship_name"):
        # A new period starts after a gap of more than 3 days.
        period = (days["date"].diff().dt.days > 3).cumsum()
        for _, p in days.groupby(period):
            if len(p) < min_days:
                continue
            start, end = p["date"].min(), p["date"].max()
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


def data_checks(records: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    """Simple data-quality checks, one row per check."""
    duplicates = records.duplicated(["ship_name", "date"], keep=False)
    over = daily[daily["capacity_factor"] > 1]
    return pd.DataFrame([
        {"check": "Records with missing production or fuel", "count": int(records["production_mwh"].isna().sum())},
        {"check": "Ship-days with more than one record", "count": int(records[duplicates][["ship_name", "date"]].drop_duplicates().shape[0])},
        {"check": "Days above the ship's maximum output (likely duplicate entry)", "count": len(over)},
    ])


def fuel_savings(df: pd.DataFrame, fuel_price: float) -> pd.DataFrame:
    """Extra fuel burned because a ship ran below its design efficiency.

    extra fuel = fuel used - fuel needed at design efficiency (operating days only)
    """
    rows = []
    for ship, days in df[df["status"] == OPERATING].groupby("ship_name"):
        mwh, fuel = days["production_mwh"].sum(), days["fuel_consumption_ton"].sum()
        design = get_ship(ship).design_mwh_per_ton
        extra = max(fuel - mwh / design, 0)
        rows.append({
            "ship_name": ship,
            "actual_mwh_per_ton": round(mwh / fuel, 2),
            "design_mwh_per_ton": design,
            "extra_fuel_t": round(extra),
            "extra_cost_usd": round(extra * fuel_price),
        })
    return pd.DataFrame(rows).sort_values("extra_cost_usd", ascending=False)
