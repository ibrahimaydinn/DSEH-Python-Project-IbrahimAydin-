"""Tests for loading, simulation, calculations and analytics."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src import analytics as A
from src.calculations import Prices, aggregate, enrich, kpis, safe_div, summarize
from src.data import DATA_PATH, daily_by_ship, load_data, normalize, read_records
from src.schema import CORE_COLUMNS, Status
from src.simulation import PRESETS, DowntimeScenario, SimulationConfig, generate_fleet

OUTAGE = DowntimeScenario(ship="Rauf Bey", start=date(2024, 7, 1), duration_days=45)


@pytest.fixture(scope="module")
def original():
    return read_records(DATA_PATH)


@pytest.fixture(scope="module")
def sim(original):
    return generate_fleet(SimulationConfig(events=(OUTAGE,)), base=original)


@pytest.fixture(scope="module")
def enriched(sim):
    return enrich(daily_by_ship(sim.dataset.records), sim.dataset.registry, Prices())


# ---------------------------------------------------------------- data
def test_original_loads_with_defaults(original):
    r = original.records
    assert list(r.columns[:4]) == CORE_COLUMNS
    assert set(r["status"]) == {Status.OPERATING.value, Status.NO_DATA.value}
    assert (r["status"] == Status.NO_DATA.value).sum() == 24
    assert set(original.registry) == {"Doğan Bey", "Kaya Bey", "Rauf Bey"}


def test_backward_compatible_load_data():
    clean, removed = load_data()
    assert removed == 24 and len(clean) == 267


def test_normalize_rejects_missing_columns():
    with pytest.raises(ValueError):
        normalize(pd.DataFrame({"ship_name": ["A"], "date": ["2024-01-01"]}))


def test_daily_by_ship_sums_duplicates(original):
    daily = daily_by_ship(original.records)
    assert not daily.duplicated(["ship_name", "date"]).any()
    assert (daily["n_records"] > 1).sum() == 21
    assert daily["production_mwh"].sum() == pytest.approx(original.records["production_mwh"].sum())


# ---------------------------------------------------------------- simulation
def test_original_rows_preserved(original, sim):
    recs = sim.dataset.records
    orig = recs[recs["source"] == "original"]
    assert len(orig) == len(original.records)
    pd.testing.assert_series_equal(
        orig["production_mwh"].reset_index(drop=True), original.records["production_mwh"].reset_index(drop=True))


def test_simulation_is_deterministic(original):
    cfg = SimulationConfig(events=(OUTAGE,), end=date(2024, 6, 30))
    a = generate_fleet(cfg, base=original).dataset.records
    b = generate_fleet(cfg, base=original).dataset.records
    pd.testing.assert_frame_equal(a, b)


def test_outage_window(sim):
    r = sim.dataset.records
    rauf = r[(r["ship_name"] == "Rauf Bey") & r["date"].between("2024-07-01", "2024-08-14")]
    assert len(rauf) == 45
    assert (rauf["status"] == Status.FORCED_OUTAGE.value).all()
    assert (rauf["production_mwh"] == 0).all()
    assert rauf["fuel_consumption_ton"].between(2.0, 4.0).all()  # standby burn
    after = r[(r["ship_name"] == "Rauf Bey") & r["date"].between("2024-08-15", "2024-08-21")]
    assert (after["status"] == Status.RAMP_UP.value).all()


def test_commissioning_date_respected(sim):
    r = sim.dataset.records
    assert r[r["ship_name"] == "Deniz Sultan"]["date"].min() == pd.Timestamp("2024-05-15")


def test_event_in_recorded_period_warns(original):
    ev = DowntimeScenario(ship="Rauf Bey", start=date(2024, 2, 1), duration_days=10)
    res = generate_fleet(SimulationConfig(events=(ev,), end=date(2024, 5, 1)), base=original)
    assert any("recorded period" in w for w in res.warnings)


def test_extend_existing_dataset(sim):
    ext = generate_fleet(SimulationConfig(end=date(2025, 3, 31)), base=sim.dataset)
    r = ext.dataset.records
    assert r["date"].max() == pd.Timestamp("2025-03-31")
    # Existing rows untouched.
    assert len(r[r["date"] <= "2024-12-31"]) == len(sim.dataset.records)


def test_presets_generate(original):
    for events in PRESETS.values():
        res = generate_fleet(SimulationConfig(events=events, end=date(2024, 10, 31)), base=original)
        assert not res.warnings


def test_realistic_ranges(enriched):
    op = enriched[enriched["status"] == Status.OPERATING.value]
    assert op["thermal_eff"].between(0.33, 0.52).mean() > 0.97
    assert op["capacity_factor"].between(0.1, 1.0).mean() > 0.97


# ---------------------------------------------------------------- calculations
def test_safe_div():
    assert safe_div(1, 0) != safe_div(1, 0)  # NaN
    s = safe_div(3600.0, pd.Series([0.0, 8000.0]))
    assert len(s) == 2 and pd.isna(s.iloc[0]) and s.iloc[1] == pytest.approx(0.45)


def test_summarize_ratio_of_sums():
    df = pd.DataFrame({"production_mwh": [100.0, 300.0], "fuel_consumption_ton": [10.0, 90.0]})
    assert summarize(df, 450, 100)["mwh_per_ton"] == pytest.approx(4.0)


def test_outage_drops_period_efficiency_and_availability(enriched):
    rauf = aggregate(enriched[enriched["ship_name"] == "Rauf Bey"], freq="M").set_index("period")
    assert rauf.loc["2024-07-01", "mwh_per_ton"] == 0  # standby burn, no output
    assert rauf.loc["2024-07-01", "availability"] == 0
    fleet = aggregate(enriched, freq="M").set_index("period")
    assert fleet.loc["2024-07-01", "availability"] < fleet.loc["2024-06-01", "availability"] - 0.1
    assert fleet.loc["2024-07-01", "capacity_factor"] < fleet.loc["2024-06-01", "capacity_factor"] - 0.05
    assert fleet.loc["2024-07-01", "thermal_eff"] < fleet.loc["2024-06-01", "thermal_eff"]


def test_kpis_keys(enriched):
    k = kpis(enriched)
    for key in ("production_mwh", "thermal_eff", "capacity_factor", "availability", "co2_intensity"):
        assert key in k and k[key] == k[key]


# ---------------------------------------------------------------- analytics
def test_outage_event_detected(enriched):
    ev = A.downtime_events(enriched)
    big = ev[ev["days"] >= 40]
    assert len(big) == 1
    row = big.iloc[0]
    assert row["ship_name"] == "Rauf Bey" and row["start"] == pd.Timestamp("2024-07-01")
    assert row["lost_mwh"] > 10_000


def test_drift_detected_before_outage(enriched):
    eps = A.drift_episodes(A.detect_anomalies(enriched))
    pre = eps[(eps["ship_name"] == "Rauf Bey") & (eps["end"] >= "2024-06-15") & (eps["end"] < "2024-07-01")]
    assert not pre.empty


def test_duplicates_flagged_over_capacity(enriched):
    an = A.detect_anomalies(enriched)
    assert (an["type"] == "Over capacity").any()


def test_savings_non_negative(enriched):
    sav = A.savings_potential(enriched, Prices(), 75)
    assert (sav["excess_fuel_t"] >= 0).all() and len(sav) == enriched["ship_name"].nunique()
