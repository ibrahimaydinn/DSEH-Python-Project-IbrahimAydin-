"""Loading, cleaning and exporting the daily powership records.

Required columns (the original file):
    ship_name, date, production_mwh, fuel_consumption_ton

Optional columns (added by the simulator, filled in when missing):
    status      operating / ramp_up / maintenance / outage / no_data
    event_note  short explanation, e.g. "Outage: crankshaft failure (day 3/45)"
    source      original / simulated / manual
"""
from io import BytesIO
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ORIGINAL_FILE = DATA_DIR / "powership_veri.xlsx"
SIMULATED_FILE = DATA_DIR / "powership_sim.xlsx"

REQUIRED_COLUMNS = ["ship_name", "date", "production_mwh", "fuel_consumption_ton"]
ALL_COLUMNS = REQUIRED_COLUMNS + ["status", "event_note", "source"]

# Ship status values
OPERATING = "operating"
RAMP_UP = "ramp_up"  # restarting after downtime, or newly commissioned
MAINTENANCE = "maintenance"  # planned downtime
OUTAGE = "outage"  # unplanned downtime (breakdown)
NO_DATA = "no_data"  # the daily report is missing

DOWN_STATUSES = [MAINTENANCE, OUTAGE]


def prepare(df: pd.DataFrame, source: str = "original") -> pd.DataFrame:
    """Check the columns, fix the types and fill in the optional columns."""
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df["production_mwh"] = pd.to_numeric(df["production_mwh"], errors="coerce")
    df["fuel_consumption_ton"] = pd.to_numeric(df["fuel_consumption_ton"], errors="coerce")

    has_values = df["production_mwh"].notna() & df["fuel_consumption_ton"].notna()
    if "status" not in df.columns:
        df["status"] = OPERATING
    df["status"] = df["status"].fillna(OPERATING)
    df.loc[~has_values, "status"] = NO_DATA

    if "event_note" not in df.columns:
        df["event_note"] = ""
    df["event_note"] = df["event_note"].fillna("")
    if "source" not in df.columns:
        df["source"] = source

    return df[ALL_COLUMNS].sort_values(["ship_name", "date"]).reset_index(drop=True)


def load_file(path) -> pd.DataFrame:
    """Read an Excel or CSV file (Excel: the 'daily' sheet, or else the first sheet)."""
    name = str(getattr(path, "name", path)).lower()
    if name.endswith(".csv"):
        df = pd.read_csv(path)
    else:
        sheets = pd.read_excel(path, sheet_name=None)
        df = sheets.get("daily", list(sheets.values())[0])
    return prepare(df)


def one_row_per_day(records: pd.DataFrame) -> pd.DataFrame:
    """Combine several records of the same ship on the same day into one row.

    Production and fuel are added up. If any record says the ship was down,
    the day counts as down.
    """
    def pick_status(statuses):
        for status in [OUTAGE, MAINTENANCE, RAMP_UP, OPERATING]:
            if status in statuses.values:
                return status
        return NO_DATA

    daily = records.groupby(["ship_name", "date"], as_index=False).agg(
        production_mwh=("production_mwh", lambda s: s.sum(min_count=1)),
        fuel_consumption_ton=("fuel_consumption_ton", lambda s: s.sum(min_count=1)),
        status=("status", pick_status),
        event_note=("event_note", lambda s: " | ".join(note for note in s if note)),
        n_records=("ship_name", "size"),
    )
    return daily


def to_excel_bytes(records: pd.DataFrame) -> bytes:
    """Excel file content for the download button."""
    buffer = BytesIO()
    save_excel(records, buffer)
    return buffer.getvalue()


def save_excel(records: pd.DataFrame, path) -> None:
    out = records.copy()
    out["date"] = out["date"].dt.date
    out.to_excel(path, sheet_name="daily", index=False)
