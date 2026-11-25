"""Behavioural profiles: how each ship's load and efficiency evolve day to day."""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from src.calculations import part_load_curve
from src.fleet import DEFAULT_REGISTRY, ShipSpec

@dataclass(frozen=True)
class ShipProfile:
    spec: ShipSpec
    base_load_factor: float = 0.60  # mean daily output / daily capacity
    load_volatility: float = 0.08  # std-dev of daily load factor
    load_persistence: float = 0.6  # AR(1) coefficient (day-to-day correlation)
    peak_mwh_per_ton: float = 5.20  # efficiency at optimal load, clean engines
    efficiency_noise: float = 0.02  # relative daily std-dev
    seasonal_amplitude: float = 0.15  # relative swing of demand over the year
    peak_month: int = 7  # month of peak demand
    hot_climate_derate: float = 0.015  # efficiency lost at the hottest point
    fouling_per_30d: float = 0.004  # efficiency drift between maintenance
    trip_rate: float = 0.010  # chance per day of a partial-day unit trip
    missing_rate: float = 0.03  # chance per day that the report is missing
    maintenance_interval_days: int = 150  # cadence of routine maintenance
    maintenance_days: int = 5

    @property
    def name(self) -> str:
        return self.spec.name


def seasonal_factor(dates: pd.DatetimeIndex, amplitude: float, peak_month: int) -> np.ndarray:
    """1 + A·cos(…) demand shape, peaking mid ``peak_month``."""
    peak_doy = pd.Timestamp(2001, peak_month, 15).dayofyear
    phase = 2 * np.pi * (dates.dayofyear.to_numpy() - peak_doy) / 365.25
    return 1.0 + amplitude * np.cos(phase)


DEFAULT_PROFILES: dict[str, ShipProfile] = {
    # Original ships: values are re-calibrated from the Excel data at runtime.
    "Doğan Bey": ShipProfile(DEFAULT_REGISTRY["Doğan Bey"], peak_month=4, hot_climate_derate=0.02),
    "Kaya Bey": ShipProfile(DEFAULT_REGISTRY["Kaya Bey"], peak_month=8),
    "Rauf Bey": ShipProfile(DEFAULT_REGISTRY["Rauf Bey"], peak_month=4, hot_climate_derate=0.02),
    # Additional fleet.
    "Selim Bey": ShipProfile(
        DEFAULT_REGISTRY["Selim Bey"], base_load_factor=0.72, load_volatility=0.06,
        peak_mwh_per_ton=5.35, seasonal_amplitude=0.10, peak_month=4,
        hot_climate_derate=0.02, maintenance_interval_days=170,
    ),
    "Nilüfer Sultan": ShipProfile(
        DEFAULT_REGISTRY["Nilüfer Sultan"], base_load_factor=0.62, load_volatility=0.09,
        peak_mwh_per_ton=6.20, seasonal_amplitude=0.22, peak_month=8,
        hot_climate_derate=0.01, fouling_per_30d=0.003, trip_rate=0.006,
    ),
    "Kerem Bey": ShipProfile(
        DEFAULT_REGISTRY["Kerem Bey"], base_load_factor=0.55, load_volatility=0.10,
        peak_mwh_per_ton=4.90, efficiency_noise=0.03, seasonal_amplitude=0.18, peak_month=5,
        hot_climate_derate=0.03, fouling_per_30d=0.007, trip_rate=0.025, missing_rate=0.05,
        maintenance_interval_days=120, maintenance_days=6,
    ),
    "Deniz Sultan": ShipProfile(
        DEFAULT_REGISTRY["Deniz Sultan"], base_load_factor=0.68, load_volatility=0.07,
        peak_mwh_per_ton=6.35, seasonal_amplitude=0.16, peak_month=5,
        hot_climate_derate=0.02, fouling_per_30d=0.003, trip_rate=0.008, missing_rate=0.02,
    ),
}


def calibrate(profile: ShipProfile, history: pd.DataFrame) -> ShipProfile:
    """Fit load level, volatility and efficiency to a ship's observed history.

    ``history`` is one row per ship-day with valid production and fuel.
    Seasonality and the part-load curve are divided out so the continuation
    matches the observed level over the observed months.
    """
    h = history.dropna(subset=["production_mwh", "fuel_consumption_ton"])
    h = h[h["production_mwh"] > 0]
    if len(h) < 14:
        return profile
    dates = pd.DatetimeIndex(h["date"])
    season = seasonal_factor(dates, profile.seasonal_amplitude, profile.peak_month)
    lf = h["production_mwh"].to_numpy() / profile.spec.daily_capacity_mwh
    base_lf = float(np.mean(lf / season))
    eff = h["production_mwh"].to_numpy() / h["fuel_consumption_ton"].to_numpy()
    peak_eff = float(np.median(eff / part_load_curve(lf)))
    # Real plant data is smoother than the uniform noise in the sample file;
    # cap the noise so efficiency anomalies remain detectable.
    eff_noise = float(min(np.std(eff) / np.mean(eff), 0.03))
    lf_vol = float(min(np.std(lf / season), 0.10))
    return replace(
        profile,
        base_load_factor=round(base_lf, 3),
        load_volatility=round(lf_vol, 3),
        peak_mwh_per_ton=round(peak_eff, 3),
        efficiency_noise=round(eff_noise, 3),
    )
