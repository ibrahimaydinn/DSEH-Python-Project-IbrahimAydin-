"""Mock data simulation: ship profiles, scenarios and the fleet generator."""
from src.simulation.generator import GenerationResult, generate_fleet, simulate_ship
from src.simulation.profiles import DEFAULT_PROFILES, ShipProfile, calibrate
from src.simulation.scenarios import (
    DEFAULT_PRESET,
    PRESETS,
    DowntimeScenario,
    SimulationConfig,
)

__all__ = [
    "DEFAULT_PRESET",
    "DEFAULT_PROFILES",
    "PRESETS",
    "DowntimeScenario",
    "GenerationResult",
    "ShipProfile",
    "SimulationConfig",
    "calibrate",
    "generate_fleet",
    "simulate_ship",
]
