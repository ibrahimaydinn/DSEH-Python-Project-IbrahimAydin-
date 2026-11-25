"""Tests: loading, simulation, calculations and alerts.  Run with: pytest"""
from datetime import date

import pandas as pd
import pytest

from karpowership import alerts as analytics, analysis
from karpowership.calculations import add_daily_metrics, summarize, summarize_by
from karpowership.data import NO_DATA, ORIGINAL_FILE, OUTAGE, RAMP_UP, add_month, load_records, one_row_per_day, prepare
from karpowership.simulation import DEFAULT_EVENT, generate_fleet


@pytest.fixture(scope="module")
def original():
    return load_records(ORIGINAL_FILE)


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
    rauf = summarize_by(add_month(daily[daily["ship_name"] == "Rauf Bey"]), ["month"]).set_index("month")
    assert rauf.loc["2024-07-01", "mwh_per_ton"] == 0  # fuel burned, nothing produced
    fleet = summarize_by(add_month(daily), ["month"]).set_index("month")
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


# ---------------------------------------------------------------- 2024 - 2026 dataset
@pytest.fixture(scope="module")
def full():
    from karpowership.simulation import build_dataset
    return build_dataset()


def test_dataset_covers_2024_to_november_2026(full):
    assert full["date"].min() == pd.Timestamp("2024-01-01")
    assert full["date"].max() == pd.Timestamp("2026-11-30")


def test_2024_is_unchanged(full, simulated):
    data_2024 = full[full["date"] <= "2024-12-31"].reset_index(drop=True)
    pd.testing.assert_frame_equal(data_2024, simulated.reset_index(drop=True))


def test_nilufer_sultan_idle_in_2026(full):
    ship = full[full["ship_name"] == "Nilüfer Sultan"].set_index("date")
    idle = ship.loc["2026-01-29":"2026-03-17"]
    assert len(idle) == 48
    assert (idle["status"] == "idle").all()
    assert (idle["production_mwh"] == 0).all()
    assert idle["fuel_consumption_ton"].between(0.5, 1.0).all()  # only heating and maintenance on board
    assert ship.loc["2026-01-28", "production_mwh"] > 0 and ship.loc["2026-03-18", "production_mwh"] > 0


def test_saved_dataset_matches_the_generator(full):
    saved = load_records()  # data/powership_data.csv
    assert len(saved) == len(full)
    assert saved["production_mwh"].sum() == pytest.approx(full["production_mwh"].sum())


# ---------------------------------------------------------------- statistics
def test_efficiency_statistics(daily):
    table = analysis.efficiency_statistics(daily)
    assert set(table["ship_name"]) == set(daily["ship_name"])
    assert (table["p10"] <= table["median"]).all() and (table["median"] <= table["p90"]).all()


def test_drop_before_rauf_outage_is_significant(daily):
    events = analytics.downtime_events(daily, 100)
    test = analysis.before_downtime_test(daily, events)
    rauf = test[test["ship_name"] == "Rauf Bey"].iloc[0]
    assert rauf["change_pct"] < 0 and rauf["significant"]


def test_seasonal_profile_has_twelve_months(daily):
    assert len(analysis.seasonal_profile(daily)) == 12
