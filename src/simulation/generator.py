"""Mock data generator.

Produces daily records in the dataset schema (core + optional columns) for
any number of ships, optionally *continuing* an existing dataset: rows of the
base data are kept untouched and each ship is simulated from the day after its
last record, with its profile calibrated on that history.

Physics-lite model per ship-day:
    load factor  = base · seasonality · demand_scale + AR(1) noise
    efficiency   = peak · part_load_curve(load) · fouling · heat derate · noise
    production   = load factor · capacity · 24 h
    fuel         = production / efficiency
Downtime days have zero output and a small standby fuel burn.
"""
from __future__ import annotations

import zlib
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

import numpy as np
import pandas as pd

from src.data import Dataset, normalize
from src.fleet import ShipSpec, infer_spec
from src.schema import STATUS_LABELS, Status
from src.simulation.profiles import (
    DEFAULT_PROFILES,
    ShipProfile,
    calibrate,
    part_load_curve,
    seasonal_factor,
)
from src.simulation.scenarios import DowntimeScenario, SimulationConfig

COMMISSIONING_DAYS = 10
MAX_FOULING_LOSS = 0.04


@dataclass
class GenerationResult:
    dataset: Dataset
    profiles: dict[str, ShipProfile]
    warnings: list[str] = field(default_factory=list)


def _rng(seed: int, name: str) -> np.random.Generator:
    """Per-ship RNG: adding or removing a ship does not change the others."""
    return np.random.default_rng([seed, zlib.crc32(name.encode())])


def routine_maintenance(
    profile: ShipProfile, start: date, end: date, rng: np.random.Generator,
    avoid: list[DowntimeScenario], margin_days: int = 25,
) -> list[DowntimeScenario]:
    """Short planned-maintenance windows at the profile's cadence, skipping
    any that would collide with an explicit scenario."""
    events: list[DowntimeScenario] = []
    interval = profile.maintenance_interval_days
    day = start + timedelta(days=int(rng.integers(30, interval)))
    while day <= end:
        ev = DowntimeScenario(
            ship=profile.name, start=day, kind=Status.PLANNED_MAINTENANCE,
            duration_days=int(profile.maintenance_days + rng.integers(-1, 2)),
            cause="Routine engine maintenance", ramp_up_days=2,
        )
        clash = any(
            ev.start <= a.end + timedelta(days=margin_days + a.ramp_up_days)
            and a.start - timedelta(days=margin_days + a.degradation_days) <= ev.end
            for a in avoid
        )
        if not clash:
            events.append(ev)
        day += timedelta(days=int(interval + rng.integers(-20, 21)))
    return events


def simulate_ship(
    profile: ShipProfile,
    start: date,
    end: date,
    events: list[DowntimeScenario],
    config: SimulationConfig,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Simulate one ship's daily records between ``start`` and ``end`` (inclusive)."""
    spec = profile.spec
    if spec.commissioned and spec.commissioned > start:
        start = spec.commissioned
    days = pd.date_range(start, end, freq="D")
    n = len(days)
    if n == 0:
        return pd.DataFrame()
    idx = {d.date(): i for i, d in enumerate(days)}

    status = np.full(n, Status.OPERATING.value, dtype=object)
    note = np.full(n, "", dtype=object)
    lf_mult = np.ones(n)
    eff_mult = np.ones(n)
    hours = np.full(n, 24.0)
    standby = np.zeros(n)
    resets: list[int] = []

    if spec.commissioned and spec.commissioned == start:
        for j in range(min(COMMISSIONING_DAYS, n)):
            frac = (j + 1) / (COMMISSIONING_DAYS + 1)
            status[j], note[j] = Status.RAMP_UP.value, f"Commissioning (day {j + 1}/{COMMISSIONING_DAYS})"
            lf_mult[j] *= 0.3 + 0.7 * frac
            eff_mult[j] *= 0.92 + 0.08 * frac
        resets.append(0)

    for ev in sorted(events, key=lambda e: e.start):
        if ev.kind == Status.FORCED_OUTAGE and ev.degradation_days > 0:
            for j in range(ev.degradation_days):
                i = idx.get(ev.start - timedelta(days=ev.degradation_days - j))
                if i is not None:
                    frac = (j + 1) / ev.degradation_days
                    eff_mult[i] *= 1 - ev.degradation_pct * frac
                    lf_mult[i] *= 1 - 0.08 * frac  # derated as vibration rises
        lo, hi = ev.fuel_range
        kind_label = STATUS_LABELS[ev.kind]
        for j in range(ev.duration_days):
            i = idx.get(ev.start + timedelta(days=j))
            if i is not None:
                status[i] = ev.kind.value
                note[i] = f"{kind_label}: {ev.label} (day {j + 1}/{ev.duration_days})"
                hours[i] = 0.0
                standby[i] = rng.uniform(lo, hi)
        for j in range(ev.ramp_up_days):
            i = idx.get(ev.end + timedelta(days=j + 1))
            if i is not None:
                frac = (j + 1) / (ev.ramp_up_days + 1)
                status[i] = Status.RAMP_UP.value
                note[i] = f"Restart after {kind_label.lower()} (day {j + 1}/{ev.ramp_up_days})"
                lf_mult[i] *= 0.35 + 0.65 * frac
                eff_mult[i] *= 0.94 + 0.06 * frac
                if j == 0:
                    hours[i] = 14.0
        if ev.restores_efficiency:
            end_i = idx.get(ev.end)
            if end_i is not None:
                resets.append(end_i)

    # Fouling drift since last maintenance (random starting point).
    since = np.empty(n)
    last = -int(rng.integers(0, profile.maintenance_interval_days))
    reset_set = set(resets)
    for i in range(n):
        if i in reset_set:
            last = i
        since[i] = i - last
    fouling = 1 - np.minimum(profile.fouling_per_30d * since / 30, MAX_FOULING_LOSS)

    # Demand / load factor.
    season = seasonal_factor(days, profile.seasonal_amplitude, profile.peak_month)
    mean_lf = profile.base_load_factor * season * config.demand_scale
    phi = profile.load_persistence
    shocks = rng.normal(0, profile.load_volatility * np.sqrt(1 - phi**2), n)
    ar = np.empty(n)
    ar[0] = rng.normal(0, profile.load_volatility)
    for i in range(1, n):
        ar[i] = phi * ar[i - 1] + shocks[i]
    lf = np.clip(mean_lf + ar, 0.15, 0.98) * lf_mult

    heat = np.clip((season - 1) / max(profile.seasonal_amplitude, 1e-6), 0, 1)
    eff = (
        profile.peak_mwh_per_ton
        * part_load_curve(lf)
        * fouling
        * (1 - profile.hot_climate_derate * heat)
        * eff_mult
        * (1 + rng.normal(0, profile.efficiency_noise, n))
    )
    production = lf * spec.daily_capacity_mwh
    fuel = production / eff

    # Unit trips on normal operating days.
    if config.trips:
        trip = (status == Status.OPERATING.value) & (rng.random(n) < profile.trip_rate)
        lost = rng.uniform(3, 14, n)
        production = np.where(trip, production * (24 - lost) / 24, production)
        fuel = np.where(trip, production / (eff * 0.97) + rng.uniform(0.8, 2.0, n), fuel)
        hours = np.where(trip, 24 - lost, hours)
        for i in np.flatnonzero(trip):
            status[i], note[i] = Status.TRIP.value, f"Unit trip: {lost[i]:.0f} h lost"

    down = np.isin(status, [Status.FORCED_OUTAGE.value, Status.PLANNED_MAINTENANCE.value, Status.DRY_DOCK.value])
    production = np.where(down, 0.0, production)
    fuel = np.where(down, standby, fuel)

    df = pd.DataFrame({
        "ship_name": profile.name,
        "date": days,
        "production_mwh": np.round(production, 1),
        "fuel_consumption_ton": np.round(fuel, 1),
        "status": status,
        "operating_hours": np.round(hours, 1),
        "event_note": note,
        "source": "simulated",
    })

    # Missing daily reports (never inside a downtime window, to keep it legible).
    if config.missing_data:
        miss = (~down) & (rng.random(n) < profile.missing_rate)
        df.loc[miss, ["production_mwh", "fuel_consumption_ton", "operating_hours"]] = np.nan
        df.loc[miss, "status"] = Status.NO_DATA.value
        df.loc[miss, "event_note"] = "Daily report missing"
    return df


def generate_fleet(
    config: SimulationConfig,
    base: Dataset | None = None,
    profiles: dict[str, ShipProfile] | None = None,
) -> GenerationResult:
    """Generate (or extend) a fleet dataset according to ``config``."""
    profiles = dict(profiles or DEFAULT_PROFILES)
    warnings: list[str] = []
    base_records = base.records if base is not None else pd.DataFrame(columns=["ship_name"])
    base_ships = list(dict.fromkeys(base_records["ship_name"]))

    names = list(config.ships) if config.ships else list(dict.fromkeys(base_ships + list(profiles)))
    frames: list[pd.DataFrame] = []
    used: dict[str, ShipProfile] = {}
    registry: dict[str, ShipSpec] = {}

    for name in names:
        history = base_records[base_records["ship_name"] == name]
        if name in profiles:
            profile = profiles[name]
        elif not history.empty:
            spec = (base.registry.get(name) if base else None) or infer_spec(name, history)
            profile = ShipProfile(spec)
        else:
            warnings.append(f"No profile for '{name}'; skipped.")
            continue

        sim_start = config.start
        if not history.empty:
            frames.append(history[(history["date"].dt.date <= config.end)])
            # Calibrate on individual records: same-day duplicates in the source
            # file would otherwise inflate the fitted load level.
            profile = calibrate(profile, history)
            sim_start = max(sim_start, history["date"].max().date() + timedelta(days=1))
        if profile.spec.commissioned and profile.spec.commissioned > sim_start:
            sim_start = profile.spec.commissioned

        rng = _rng(config.seed, name)
        explicit = [e for e in config.events if e.ship == name]
        for e in explicit:
            if e.end < sim_start:
                warnings.append(
                    f"{STATUS_LABELS[e.kind]} for {name} starting {e.start} falls in the "
                    f"recorded period (before {sim_start}); it was not applied."
                )
        events = list(explicit)
        if config.routine_maintenance:
            events += routine_maintenance(profile, sim_start, config.end, rng, explicit)

        sim = simulate_ship(profile, sim_start, config.end, events, config, rng)
        if not sim.empty:
            frames.append(sim)
        used[name] = profile
        registry[name] = profile.spec

    for e in config.events:
        if e.ship not in used:
            warnings.append(f"Scenario ship '{e.ship}' is not in the simulated fleet.")

    frames = [f for f in frames if not f.empty]
    records = normalize(pd.concat(frames, ignore_index=True)) if frames else normalize(
        pd.DataFrame(columns=["ship_name", "date", "production_mwh", "fuel_consumption_ton"])
    )
    return GenerationResult(Dataset(records, registry), used, warnings)


def with_overrides(profile: ShipProfile, **changes) -> ShipProfile:
    """Convenience for experiments, e.g. ``with_overrides(p, trip_rate=0.05)``."""
    return replace(profile, **changes)
