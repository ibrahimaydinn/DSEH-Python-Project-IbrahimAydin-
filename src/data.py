"""Data loading, schema normalisation and persistence for the powership dataset.

Any file with the four core columns loads. Optional columns (status,
operating_hours, event_note, source) are filled with defaults when absent, so
the original ``powership_veri.xlsx`` and simulator output share one code path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

import pandas as pd

from src.fleet import ShipSpec, build_registry, registry_from_frame, registry_to_frame
from src.schema import ALL_COLUMNS, CORE_COLUMNS, STATUS_PRIORITY, Status

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_PATH = DATA_DIR / "powership_veri.xlsx"
SIM_PATH = DATA_DIR / "powership_sim.xlsx"
REQUIRED = ["production_mwh", "fuel_consumption_ton"]

RECORDS_SHEET = "daily"
SHIPS_SHEET = "ships"


@dataclass
class Dataset:
    records: pd.DataFrame  # one row per record (ship-days may repeat), normalised
    registry: dict[str, ShipSpec] = field(default_factory=dict)

    @property
    def clean(self) -> pd.DataFrame:
        """Records with both production and fuel present."""
        return self.records.dropna(subset=REQUIRED)


def normalize(df: pd.DataFrame, source: str = "original") -> pd.DataFrame:
    """Coerce types and add optional columns with sensible defaults."""
    missing = [c for c in CORE_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Dataset is missing required columns: {missing}")
    out = df.copy()
    out["ship_name"] = out["ship_name"].astype(str).str.strip()
    out["date"] = pd.to_datetime(out["date"]).dt.normalize()
    for col in REQUIRED:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    has_values = out[REQUIRED].notna().all(axis=1)
    default_status = has_values.map({True: Status.OPERATING.value, False: Status.NO_DATA.value})
    if "status" not in out.columns:
        out["status"] = default_status
    else:
        out["status"] = out["status"].where(out["status"].notna(), default_status).astype(str)

    if "operating_hours" not in out.columns:
        out["operating_hours"] = has_values.map({True: 24.0, False: float("nan")})
    out["operating_hours"] = pd.to_numeric(out["operating_hours"], errors="coerce")
    if "event_note" not in out.columns:
        out["event_note"] = ""
    out["event_note"] = out["event_note"].fillna("").astype(str)
    if "source" not in out.columns:
        out["source"] = source
    out["source"] = out["source"].fillna(source).astype(str)

    extra = [c for c in out.columns if c not in ALL_COLUMNS]
    return out[ALL_COLUMNS + extra].sort_values(["ship_name", "date"], kind="stable").reset_index(drop=True)


def read_records(src: str | Path | BinaryIO, source: str = "original") -> Dataset:
    """Read an .xlsx (``daily`` sheet or first sheet, optional ``ships`` sheet) or .csv."""
    name = str(getattr(src, "name", src)).lower()
    overrides: dict[str, ShipSpec] = {}
    if name.endswith(".csv"):
        raw = pd.read_csv(src)
    else:
        sheets = pd.read_excel(src, sheet_name=None)
        raw = sheets.get(RECORDS_SHEET, next(iter(sheets.values())))
        if SHIPS_SHEET in sheets:
            overrides = registry_from_frame(sheets[SHIPS_SHEET])
    records = normalize(raw, source=source)
    return Dataset(records, build_registry(records, overrides))


def load_data(path: Path = DATA_PATH) -> tuple[pd.DataFrame, int]:
    """Backward-compatible loader: cleaned records and number of rows removed."""
    ds = read_records(path)
    clean = ds.clean.copy()
    clean["date"] = clean["date"].dt.date
    return clean, len(ds.records) - len(clean)


def daily_by_ship(records: pd.DataFrame) -> pd.DataFrame:
    """Collapse to one row per ship-day.

    Production and fuel are summed (ratio of sums downstream); status takes the
    most severe value; ``n_records`` flags days with several entries.
    """
    rank = {s.value: i for i, s in enumerate(STATUS_PRIORITY)}
    df = records.assign(_rank=records["status"].map(rank).fillna(len(rank)))
    grouped = df.groupby(["ship_name", "date"], sort=True)
    out = grouped.agg(
        production_mwh=("production_mwh", lambda s: s.sum(min_count=1)),
        fuel_consumption_ton=("fuel_consumption_ton", lambda s: s.sum(min_count=1)),
        operating_hours=("operating_hours", "max"),
        event_note=("event_note", lambda s: " | ".join(dict.fromkeys(x for x in s if x))),
        source=("source", "first"),
        n_records=("ship_name", "size"),
        _rank=("_rank", "min"),
    ).reset_index()
    inv = {i: s.value for i, s in enumerate(STATUS_PRIORITY)}
    out["status"] = out.pop("_rank").map(inv).fillna(Status.NO_DATA.value)
    # A ship-day with some valid records is not "no data".
    valid = out[REQUIRED].notna().all(axis=1)
    out.loc[valid & (out["status"] == Status.NO_DATA.value), "status"] = Status.OPERATING.value
    return out


def to_excel_bytes(records: pd.DataFrame, registry: dict[str, ShipSpec]) -> bytes:
    buf = BytesIO()
    write_excel(buf, records, registry)
    return buf.getvalue()


def write_excel(dest: str | Path | BinaryIO, records: pd.DataFrame, registry: dict[str, ShipSpec]) -> None:
    """Write records (``daily`` sheet) and ship metadata (``ships`` sheet)."""
    out = records.copy()
    out["date"] = out["date"].dt.date
    with pd.ExcelWriter(dest, engine="openpyxl") as xw:
        out.to_excel(xw, sheet_name=RECORDS_SHEET, index=False)
        registry_to_frame(registry).to_excel(xw, sheet_name=SHIPS_SHEET, index=False)
