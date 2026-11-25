"""Column schema and operational status vocabulary shared by all modules."""
from __future__ import annotations

from enum import StrEnum

# Core columns: the original dataset contract. Every file must have these.
CORE_COLUMNS = ["ship_name", "date", "production_mwh", "fuel_consumption_ton"]

# Optional columns added by the simulator. Files without them still load:
# defaults are derived in ``data.normalize``.
OPTIONAL_COLUMNS = ["status", "operating_hours", "event_note", "source"]

ALL_COLUMNS = CORE_COLUMNS + OPTIONAL_COLUMNS


class Status(StrEnum):
    OPERATING = "operating"
    RAMP_UP = "ramp_up"  # commissioning or restart after downtime
    TRIP = "trip"  # partial-day unit trip
    PLANNED_MAINTENANCE = "planned_maintenance"
    DRY_DOCK = "dry_dock"
    FORCED_OUTAGE = "forced_outage"
    NO_DATA = "no_data"  # record missing / not reported


# Ship is producing (possibly at reduced output).
AVAILABLE = {Status.OPERATING, Status.RAMP_UP, Status.TRIP}
# Ship is out of service.
DOWNTIME = {Status.PLANNED_MAINTENANCE, Status.DRY_DOCK, Status.FORCED_OUTAGE}

# When several records fall on the same ship-day, the most severe wins.
STATUS_PRIORITY = [
    Status.FORCED_OUTAGE,
    Status.DRY_DOCK,
    Status.PLANNED_MAINTENANCE,
    Status.TRIP,
    Status.RAMP_UP,
    Status.OPERATING,
    Status.NO_DATA,
]

STATUS_LABELS = {
    Status.OPERATING: "Operating",
    Status.RAMP_UP: "Ramp-up",
    Status.TRIP: "Unit trip",
    Status.PLANNED_MAINTENANCE: "Planned maintenance",
    Status.DRY_DOCK: "Dry-dock",
    Status.FORCED_OUTAGE: "Forced outage",
    Status.NO_DATA: "No data",
}
