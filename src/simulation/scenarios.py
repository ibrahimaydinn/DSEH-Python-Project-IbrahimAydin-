"""Scenario definitions: operational events injected into the simulated data.

Add a new scenario by creating a ``DowntimeScenario`` (or a preset in
``PRESETS``); the generator turns it into per-day status, output and fuel.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from src.schema import Status

# Typical standby fuel burn per day (min, max tonnes) while out of service:
# hotel load, HFO tank heating and preservation. Dry-dock ships are on shore
# power, so burn is low.
STANDBY_FUEL_T: dict[Status, tuple[float, float]] = {
    Status.FORCED_OUTAGE: (2.0, 4.0),
    Status.PLANNED_MAINTENANCE: (1.5, 3.0),
    Status.DRY_DOCK: (0.3, 1.0),
}

DEFAULT_CAUSES: dict[Status, str] = {
    Status.FORCED_OUTAGE: "Main engine crankshaft bearing failure",
    Status.PLANNED_MAINTENANCE: "Scheduled engine overhaul",
    Status.DRY_DOCK: "Class renewal dry-docking",
}


@dataclass(frozen=True)
class DowntimeScenario:
    """A ship is out of service for ``duration_days``.

    For forced outages a degradation precursor (rising fuel burn per MWh) can
    precede the failure; every event is followed by a ramp-up.
    """

    ship: str
    start: date
    duration_days: int = 45
    kind: Status = Status.FORCED_OUTAGE
    cause: str = ""
    degradation_days: int = 21  # only applied to forced outages
    degradation_pct: float = 0.09  # efficiency loss reached just before failure
    ramp_up_days: int = 7
    standby_fuel_t: tuple[float, float] | None = None  # None -> STANDBY_FUEL_T[kind]
    restores_efficiency: bool = True  # resets fouling drift after the event

    @property
    def end(self) -> date:
        """Last day of downtime (inclusive)."""
        return self.start + timedelta(days=self.duration_days - 1)

    @property
    def label(self) -> str:
        return self.cause or DEFAULT_CAUSES.get(self.kind, str(self.kind))

    @property
    def fuel_range(self) -> tuple[float, float]:
        return self.standby_fuel_t or STANDBY_FUEL_T.get(self.kind, (1.0, 2.0))


@dataclass(frozen=True)
class SimulationConfig:
    start: date = date(2024, 1, 1)
    end: date = date(2024, 12, 31)
    seed: int = 42
    ships: tuple[str, ...] = ()  # empty -> all known profiles
    events: tuple[DowntimeScenario, ...] = ()
    routine_maintenance: bool = True
    trips: bool = True
    missing_data: bool = True
    demand_scale: float = 1.0  # fleet-wide demand multiplier (e.g. 0.9 for a soft year)


HEADLINE_OUTAGE = DowntimeScenario(ship="Rauf Bey", start=date(2024, 7, 1), duration_days=45)

PRESETS: dict[str, tuple[DowntimeScenario, ...]] = {
    "Rauf Bey forced outage (45 days, July–Aug)": (HEADLINE_OUTAGE,),
    "Kaya Bey dry-dock (45 days, planned)": (
        DowntimeScenario(ship="Kaya Bey", start=date(2024, 9, 2), duration_days=45, kind=Status.DRY_DOCK),
    ),
    "Double hit: Rauf Bey outage + Kerem Bey overhaul": (
        HEADLINE_OUTAGE,
        DowntimeScenario(
            ship="Kerem Bey", start=date(2024, 7, 20), duration_days=14,
            kind=Status.PLANNED_MAINTENANCE,
        ),
    ),
    "Baseline (routine maintenance only)": (),
}
DEFAULT_PRESET = next(iter(PRESETS))
