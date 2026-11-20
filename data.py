"""Data loading and cleaning for the powership dataset."""
from pathlib import Path

import pandas as pd

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "powership_veri.xlsx"
REQUIRED = ["production_mwh", "fuel_consumption_ton"]


def load_data(path: Path = DATA_PATH) -> tuple[pd.DataFrame, int]:
    """Read the Excel file and drop rows with missing production or fuel values.

    Returns the cleaned DataFrame and the number of rows removed.
    """
    raw = pd.read_excel(path)
    clean = raw.dropna(subset=REQUIRED).copy()
    clean["date"] = pd.to_datetime(clean["date"]).dt.date
    return clean, len(raw) - len(clean)
