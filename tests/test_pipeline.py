"""Tests: loading, simulation, calculations and alerts.  Run with: pytest"""
from datetime import date

import pandas as pd
import pytest

from src import analytics
from src.calculations import add_daily_metrics, add_period, summarize, summarize_by
from src.data import NO_DATA, ORIGINAL_FILE, OUTAGE, RAMP_UP, load_file, one_row_per_day, prepare
from src.simulation import DEFAULT_EVENT, generate_fleet


@pytest.fixture(scope="module")
def original():
    return load_file(ORIGINAL_FILE)


@pytest.fixture(scope="module")
def simulated(original):
    return generate_fleet(original, date(2024, 12, 31), [DEFAULT_EVENT])


@pytest.fixture(scope="module")
def daily(simulated):
    return add_daily_metrics(one_row_per_day(simulated), fuel_price=450, electricity_price=100)


def test_original_file_loads(original):
    assert len(original) == 291
    assert (original["status"] == NO_DATA).sum() == 24
    assert set(original["ship_name"]) == {"Doğan Bey", "Kaya Bey", "Rauf Bey"}


def test_missing_columns_are_rejected():
    with pytest.raises(ValueError):
        prepare(pd.DataFrame({"ship_name": ["A"], "date": ["2024-01-01"]}))


def test_duplicates_are_combined(original):
    days = one_row_per_day(original)
    assert not days.duplicated(["ship_name", "date"]).any()
    assert days["production_mwh"].sum() == pytest.approx(original["production_mwh"].sum())


def test_original_rows_are_kept(original, simulated):
    kept = simulated[simulated["source"] == "original"]
    assert len(kept) == len(original)


def test_same_seed_same_data(original):
    a = generate_fleet(original, date(2024, 6, 30), [])
    b = generate_fleet(original, date(2024, 6, 30), [])
    pd.testing.assert_frame_equal(a, b)


def test_outage_days(simulated):
    rauf = simulated[simulated["ship_name"] == "Rauf Bey"].set_index("date")
    outage = rauf.loc["2024-07-01":"2024-08-14"]
    assert len(outage) == 45
    assert (outage["status"] == OUTAGE).all()
    assert (outage["production_mwh"] == 0).all()
    assert outage["fuel_consumption_ton"].between(2, 4).all()  # standby fuel
    assert (rauf.loc["2024-08-15":"2024-08-21", "status"] == RAMP_UP).all()


def test_new_ship_starts_on_its_first_day(simulated):
    assert simulated[simulated["ship_name"] == "Deniz Sultan"]["date"].min() == pd.Timestamp("2024-05-15")


def test_period_totals_use_total_divided_by_total():
    df = pd.DataFrame({"ship_name": "Rauf Bey", "date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
                       "production_mwh": [100.0, 300.0], "fuel_consumption_ton": [10.0, 90.0],
                       "status": "operating", "event_note": ""})
    assert summarize(add_daily_metrics(df, 450, 100))["mwh_per_ton"] == pytest.approx(4.0)


def test_outage_lowers_efficiency_and_availability(daily):
    rauf = summarize_by(add_period(daily[daily["ship_name"] == "Rauf Bey"], "M"), ["period"]).set_index("period")
    assert rauf.loc["2024-07-01", "mwh_per_ton"] == 0  # fuel burned, nothing produced
    fleet = summarize_by(add_period(daily, "M"), ["period"]).set_index("period")
    assert fleet.loc["2024-07-01", "availability"] < fleet.loc["2024-06-01", "availability"] - 0.1


def test_outage_found_as_event(daily):
    events = analytics.downtime_events(daily, electricity_price=100)
    long = events[events["days"] >= 40]
    assert list(long["ship_name"]) == ["Rauf Bey"]
    assert long["lost_mwh"].iloc[0] > 10_000


def test_early_warning_before_outage(daily):
    events = analytics.downtime_events(daily, 100)
    alerts = analytics.efficiency_alerts(analytics.efficiency_check(daily), events)
    warning = alerts[(alerts["ship_name"] == "Rauf Bey") & (alerts["followed_by"] == "Outage")]
    assert not warning.empty


def test_data_checks_find_duplicates(simulated, daily):
    checks = analytics.data_checks(simulated, daily).set_index("check")["count"]
    assert checks["Ship-days with more than one record"] == 21
