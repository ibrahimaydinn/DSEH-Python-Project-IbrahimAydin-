"""The fleet: fixed information about each powership.

All ships burn heavy fuel oil (HFO), so "MWh per tonne of fuel" can be
compared directly between ships.
"""
from dataclasses import asdict, dataclass
from datetime import date

import pandas as pd

CO2_PER_TON_FUEL = 3.114  # tonnes of CO2 released per tonne of HFO burned


@dataclass(frozen=True)
class Ship:
    name: str
    capacity_mw: float  # maximum electrical output
    site: str
    design_mwh_per_ton: float  # efficiency the engines are designed to reach
    first_day: date | None = None  # first day in service (None = already running)

    @property
    def max_mwh_per_day(self) -> float:
        return self.capacity_mw * 24


# The three ships in the original Excel file. Their capacity is not in the
# data; 25 MW is an assumption that fits the observed 200-480 MWh per day.
ORIGINAL_SHIPS = [
    Ship("Doğan Bey", 25, "West Africa", 5.30),
    Ship("Kaya Bey", 25, "Mediterranean", 5.30),
    Ship("Rauf Bey", 25, "West Africa", 5.30),
]

# Fictional ships added for the simulation.
NEW_SHIPS = [
    Ship("Selim Bey", 36, "West Africa", 5.40),
    Ship("Nilüfer Sultan", 30, "Mediterranean", 5.20),
    Ship("Kerem Bey", 20, "South Asia", 4.90),
    Ship("Deniz Sultan", 42, "South Asia", 5.50, first_day=date(2024, 5, 15)),
]

ALL_SHIPS = {ship.name: ship for ship in ORIGINAL_SHIPS + NEW_SHIPS}


def get_ship(name):
    """
    Look up a ship by name. Unknown ships (e.g. added by hand) get default values.

    Parameters
    ----------
    name : str

    Returns
    -------
    Ship
    """
    return ALL_SHIPS.get(name, Ship(name, 25, "Unknown", 5.00))


def ship_table(names):
    """
    The ship information as a table, one row per ship (used to merge with the records).

    Parameters
    ----------
    names : list of str

    Returns
    -------
    pandas.DataFrame
        Columns ``ship_name``, ``capacity_mw``, ``site``, ``design_mwh_per_ton``.
    """
    rows = [asdict(get_ship(name)) for name in names]
    table = pd.DataFrame(rows).rename(columns={"name": "ship_name"})
    return table.drop(columns="first_day")
