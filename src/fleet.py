"""Fleet registry: static metadata for each powership and fuel properties.

The daily dataset only carries ``ship_name``; everything that does not change
day to day (installed capacity, fuel type, site) lives here. Ships that appear
in a dataset but not in the registry get an inferred spec (see
:func:`infer_spec`) so any Excel/CSV with the core columns still works.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum

import pandas as pd


class FuelType(StrEnum):
    HFO = "HFO"
    LNG = "LNG"
    MGO = "MGO"


@dataclass(frozen=True)
class FuelProperties:
    lhv_mj_per_kg: float  # lower heating value
    co2_t_per_t: float  # IMO-style carbon factor (t CO2 per t fuel)
    default_price_usd_t: float  # placeholder price, adjustable in the UI


FUELS: dict[FuelType, FuelProperties] = {
    FuelType.HFO: FuelProperties(lhv_mj_per_kg=40.2, co2_t_per_t=3.114, default_price_usd_t=450.0),
    FuelType.LNG: FuelProperties(lhv_mj_per_kg=48.0, co2_t_per_t=2.750, default_price_usd_t=560.0),
    FuelType.MGO: FuelProperties(lhv_mj_per_kg=42.7, co2_t_per_t=3.206, default_price_usd_t=720.0),
}


@dataclass(frozen=True)
class ShipSpec:
    name: str
    capacity_mw: float  # contracted / installed net output
    fuel_type: FuelType = FuelType.HFO
    site: str = "Unassigned"
    commissioned: date | None = None  # first day of commercial operation
    design_mwh_per_ton: float | None = None  # nameplate efficiency at optimal load

    @property
    def daily_capacity_mwh(self) -> float:
        return self.capacity_mw * 24.0

    def to_row(self) -> dict:
        row = asdict(self)
        row["fuel_type"] = str(self.fuel_type)
        return row


# Ships in the original dataset. Capacity is an assumption chosen so that the
# observed daily output (≈200–480 MWh) maps to a 35–80 % load factor.
ORIGINAL_SHIPS: tuple[ShipSpec, ...] = (
    ShipSpec("Doğan Bey", 25.0, FuelType.HFO, "West Africa", design_mwh_per_ton=5.30),
    ShipSpec("Kaya Bey", 25.0, FuelType.HFO, "Mediterranean", design_mwh_per_ton=5.30),
    ShipSpec("Rauf Bey", 25.0, FuelType.HFO, "West Africa", design_mwh_per_ton=5.30),
)

# Fictional additional vessels for simulation.
EXTRA_SHIPS: tuple[ShipSpec, ...] = (
    ShipSpec("Selim Bey", 36.0, FuelType.HFO, "West Africa", design_mwh_per_ton=5.40),
    ShipSpec("Nilüfer Sultan", 30.0, FuelType.LNG, "Mediterranean", design_mwh_per_ton=6.25),
    ShipSpec("Kerem Bey", 20.0, FuelType.HFO, "South Asia", design_mwh_per_ton=4.95),
    ShipSpec(
        "Deniz Sultan", 42.0, FuelType.LNG, "South Asia",
        commissioned=date(2024, 5, 15), design_mwh_per_ton=6.40,
    ),
)

DEFAULT_REGISTRY: dict[str, ShipSpec] = {s.name: s for s in ORIGINAL_SHIPS + EXTRA_SHIPS}


def infer_spec(name: str, records: pd.DataFrame) -> ShipSpec:
    """Build a spec for an unknown ship from its records (P95 output ≈ 85 % load)."""
    daily = records.groupby("date")["production_mwh"].sum()
    p95 = float(daily.quantile(0.95)) if daily.notna().any() else 240.0
    capacity = max(round(p95 / 24 / 0.85), 1)
    return ShipSpec(name, float(capacity))


def build_registry(
    records: pd.DataFrame, overrides: dict[str, ShipSpec] | None = None
) -> dict[str, ShipSpec]:
    """Registry covering every ship in ``records`` (overrides > defaults > inferred)."""
    known = {**DEFAULT_REGISTRY, **(overrides or {})}
    registry: dict[str, ShipSpec] = {}
    for name in records["ship_name"].dropna().unique():
        registry[name] = known.get(name) or infer_spec(name, records[records["ship_name"] == name])
    return registry


def registry_to_frame(registry: dict[str, ShipSpec]) -> pd.DataFrame:
    return pd.DataFrame([s.to_row() for s in registry.values()])


def registry_from_frame(frame: pd.DataFrame) -> dict[str, ShipSpec]:
    specs: dict[str, ShipSpec] = {}
    for row in frame.to_dict("records"):
        commissioned = row.get("commissioned")
        design = row.get("design_mwh_per_ton")
        specs[row["name"]] = ShipSpec(
            name=row["name"],
            capacity_mw=float(row["capacity_mw"]),
            fuel_type=FuelType(row.get("fuel_type") or "HFO"),
            site=row.get("site") or "Unassigned",
            commissioned=pd.Timestamp(commissioned).date() if pd.notna(commissioned) else None,
            design_mwh_per_ton=float(design) if pd.notna(design) else None,
        )
    return specs


def ship_order(registry: dict[str, ShipSpec]) -> list[str]:
    """Stable ship order (registry order first) so chart colors follow the ship."""
    default = [n for n in DEFAULT_REGISTRY if n in registry]
    return default + sorted(n for n in registry if n not in DEFAULT_REGISTRY)
