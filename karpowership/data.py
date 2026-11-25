"""
Load, clean and reshape the daily powership records with pandas.

Required columns (the original Excel file):
    ship_name, date, production_mwh, fuel_consumption_ton

Optional columns (added by the simulator, filled in when missing):
    status      operating / ramp_up / maintenance / outage / idle / no_data
    event_note  short explanation, e.g. "Outage: crankshaft failure (day 3/45)"
    source      original / simulated / manual
"""

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ORIGINAL_FILE = DATA_DIR / "powership_veri.xlsx"  # the real records (Jan - Mar 2024)
DATASET_FILE = DATA_DIR / "powership_data.csv"  # the full dataset used by the app

REQUIRED_COLUMNS = ["ship_name", "date", "production_mwh", "fuel_consumption_ton"]
ALL_COLUMNS = REQUIRED_COLUMNS + ["status", "event_note", "source"]

# Ship status values
OPERATING = "operating"
RAMP_UP = "ramp_up"  # restarting after downtime, or newly commissioned
MAINTENANCE = "maintenance"  # planned downtime
OUTAGE = "outage"  # unplanned downtime (breakdown)
IDLE = "idle"  # the ship works but cannot deliver power (e.g. no grid connection)
NO_DATA = "no_data"  # the daily report is missing

DOWN_STATUSES = [MAINTENANCE, OUTAGE, IDLE]


def prepare(df, source="original"):
    """
    Clean a table of records: check the columns, fix the types, fill the optional columns.

    Parameters
    ----------
    df : pandas.DataFrame
        Must contain the four required columns.
    source : str, optional
        Value for the ``source`` column when it is missing.

    Returns
    -------
    pandas.DataFrame
        The cleaned records, sorted by ship and date.
    """
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df["production_mwh"] = pd.to_numeric(df["production_mwh"], errors="coerce")
    df["fuel_consumption_ton"] = pd.to_numeric(df["fuel_consumption_ton"], errors="coerce")

    if "status" not in df.columns:
        df["status"] = OPERATING
    df["status"] = df["status"].fillna(OPERATING)
    has_values = df["production_mwh"].notna() & df["fuel_consumption_ton"].notna()
    df.loc[~has_values, "status"] = NO_DATA

    if "event_note" not in df.columns:
        df["event_note"] = ""
    df["event_note"] = df["event_note"].fillna("")
    if "source" not in df.columns:
        df["source"] = source

    return df[ALL_COLUMNS].sort_values(["ship_name", "date"]).reset_index(drop=True)


def load_records(path=DATASET_FILE):
    """
    Read records from a CSV or Excel file and clean them.

    Parameters
    ----------
    path : str or pathlib.Path, optional
        Default: the full dataset ``data/powership_data.csv``.

    Returns
    -------
    pandas.DataFrame
    """
    if str(path).endswith(".csv"):
        return prepare(pd.read_csv(path))
    return prepare(pd.read_excel(path))


def save_records(records, path=DATASET_FILE):
    """
    Save records as CSV (dates written as YYYY-MM-DD).

    Parameters
    ----------
    records : pandas.DataFrame
    path : str or pathlib.Path, optional
    """
    records.assign(date=records["date"].dt.date).to_csv(path, index=False)


def one_row_per_day(records):
    """
    Combine several records of the same ship on the same day into one row.

    Production and fuel are added up. If any record says the ship was down,
    the whole day counts as down.

    Parameters
    ----------
    records : pandas.DataFrame

    Returns
    -------
    pandas.DataFrame
        One row per ship and day, with an extra ``n_records`` column.
    """
    def pick_status(statuses):
        for status in [OUTAGE, IDLE, MAINTENANCE, RAMP_UP, OPERATING]:
            if status in statuses.values:
                return status
        return NO_DATA

    return records.groupby(["ship_name", "date"], as_index=False).agg(
        production_mwh=("production_mwh", lambda s: s.sum(min_count=1)),
        fuel_consumption_ton=("fuel_consumption_ton", lambda s: s.sum(min_count=1)),
        status=("status", pick_status),
        event_note=("event_note", lambda s: " | ".join(note for note in s if note)),
        n_records=("ship_name", "size"),
    )


def add_month(df):
    """
    Add a ``month`` column with the first day of the month.

    Parameters
    ----------
    df : pandas.DataFrame
        Must contain a ``date`` column.

    Returns
    -------
    pandas.DataFrame
    """
    return df.assign(month=df["date"].dt.to_period("M").dt.start_time)


def monthly_table(monthly, value):
    """
    Reshape a long table (one row per ship and month) into a wide one.

    Parameters
    ----------
    monthly : pandas.DataFrame
        Columns ``ship_name``, ``month`` and ``value``.
    value : str
        The column to spread, e.g. ``"availability"``.

    Returns
    -------
    pandas.DataFrame
        One row per ship, one column per month.
    """
    return monthly.pivot_table(index="ship_name", columns="month", values=value)
