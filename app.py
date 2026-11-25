"""Karowership fleet operations & optimisation dashboard (Streamlit).

Run with:  streamlit run app.py
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from src import analytics as A
from src.calculations import Prices, enrich
from src.data import DATA_PATH, Dataset, daily_by_ship, normalize, read_records
from src.fleet import EXTRA_SHIPS, FUELS, FuelType, ShipSpec, ship_order
from src.schema import STATUS_LABELS, Status
from src.simulation import DEFAULT_PRESET, PRESETS, DowntimeScenario, SimulationConfig, generate_fleet
from src.ui import charts as C
from src.ui import views as V

st.set_page_config(page_title="Karowership Fleet Ops", page_icon="⚡", layout="wide")

SOURCES = ["Scenario simulator", "Original Excel", "Upload file"]
CUSTOM = "Custom scenario…"
FREQS = {"Daily": "D", "Weekly": "W", "Monthly": "M"}


# ------------------------------------------------------------------ data
@st.cache_data(show_spinner=False)
def load_original() -> Dataset:
    return read_records(DATA_PATH)


@st.cache_data(show_spinner="Simulating fleet…")
def simulate(config: SimulationConfig, continue_original: bool):
    base = load_original() if continue_original else None
    return generate_fleet(config, base=base)


@st.cache_data(show_spinner=False)
def load_upload(content: bytes, name: str) -> Dataset:
    from io import BytesIO
    buf = BytesIO(content)
    buf.name = name
    return read_records(buf, source="upload")


def scenario_sidebar() -> tuple[SimulationConfig, bool]:
    with st.sidebar.expander("Scenario", expanded=True):
        preset = st.selectbox("Downtime scenario", list(PRESETS) + [CUSTOM], index=0)
        all_ships = ["Doğan Bey", "Kaya Bey", "Rauf Bey"] + [s.name for s in EXTRA_SHIPS]
        if preset == CUSTOM:
            ship = st.selectbox("Ship", all_ships, index=2)
            kind = st.selectbox("Event type", [Status.FORCED_OUTAGE, Status.PLANNED_MAINTENANCE, Status.DRY_DOCK],
                                format_func=lambda s: STATUS_LABELS[s])
            start = st.date_input("Start", value=date(2024, 7, 1), min_value=date(2024, 1, 1))
            days = st.slider("Duration (days)", 3, 120, 45)
            degr = 0
            if kind == Status.FORCED_OUTAGE:
                degr = st.slider("Degradation before failure (days)", 0, 45, 21)
            cause = st.text_input("Cause", value="")
            events = (DowntimeScenario(ship=ship, start=start, duration_days=days, kind=kind,
                                       cause=cause, degradation_days=degr),)
        else:
            events = PRESETS[preset]
        st.caption(" · ".join(f"{e.ship}: {STATUS_LABELS[e.kind].lower()} from {e.start:%d %b}, {e.duration_days} d"
                              for e in events) or "No major event.")

    with st.sidebar.expander("Fleet & horizon"):
        continue_original = st.checkbox("Start from original Excel records", value=True,
                                        help="Keep the recorded Jan–Mar 2024 data and simulate onward.")
        extra = st.multiselect("Additional ships", [s.name for s in EXTRA_SHIPS],
                               default=[s.name for s in EXTRA_SHIPS])
        end = st.date_input("Simulate until", value=date(2024, 12, 31),
                            min_value=date(2024, 4, 30), max_value=date(2027, 12, 31))
        demand = st.slider("Demand scale", 0.7, 1.2, 1.0, 0.05, help="Fleet-wide demand multiplier.")
        a, b = st.columns(2)
        routine = a.checkbox("Routine maint.", value=True)
        trips = b.checkbox("Unit trips", value=True)
        missing = a.checkbox("Missing reports", value=True)
        seed = b.number_input("Seed", value=42, step=1)
    ships = tuple(["Doğan Bey", "Kaya Bey", "Rauf Bey"] + extra)
    config = SimulationConfig(
        start=date(2024, 1, 1), end=end, seed=int(seed), ships=ships, events=tuple(events),
        routine_maintenance=routine, trips=trips, missing_data=missing, demand_scale=demand,
    )
    return config, continue_original


def add_manual_record(row: dict, capacity: float, fuel_type: str) -> None:
    st.session_state.setdefault("manual_records", []).append(row)
    st.session_state.setdefault("manual_specs", {})[row["ship_name"]] = ShipSpec(
        row["ship_name"], capacity, FuelType(fuel_type))


# ------------------------------------------------------------------ sidebar
st.sidebar.title("⚡ Karowership")
source = st.sidebar.radio("Data source", SOURCES, index=0)
profiles = None
warnings: list[str] = []
if source == "Scenario simulator":
    config, cont = scenario_sidebar()
    result = simulate(config, cont)
    dataset, profiles, warnings = result.dataset, result.profiles, result.warnings
elif source == "Original Excel":
    dataset = load_original()
else:
    up = st.sidebar.file_uploader("Excel or CSV with ship_name, date, production_mwh, fuel_consumption_ton",
                                  type=["xlsx", "csv"])
    if up is None:
        st.info("Upload a file in the sidebar to continue.")
        st.stop()
    try:
        dataset = load_upload(up.getvalue(), up.name)
    except ValueError as exc:
        st.error(str(exc))
        st.stop()

# Session-added records.
manual = st.session_state.get("manual_records", [])
if manual:
    registry = {**dataset.registry}
    for name, spec in st.session_state.get("manual_specs", {}).items():
        registry.setdefault(name, spec)
    records = normalize(pd.concat([dataset.records, pd.DataFrame(manual)], ignore_index=True))
    dataset = Dataset(records, registry)
    if st.sidebar.button(f"Clear {len(manual)} added record(s)"):
        st.session_state["manual_records"] = []
        st.rerun()

daily_all = daily_by_ship(dataset.records)
order = ship_order(dataset.registry)

st.sidebar.header("Filters")
ships = st.sidebar.multiselect("Ships", order, default=order)
dmin, dmax = daily_all["date"].min().date(), daily_all["date"].max().date()
rng = st.sidebar.date_input("Date range", value=(dmin, dmax), min_value=dmin, max_value=dmax)
start, end = (rng if isinstance(rng, tuple) and len(rng) == 2 else (dmin, dmax))
freq_label = st.sidebar.radio("Granularity", list(FREQS), index=1, horizontal=True)

with st.sidebar.expander("Prices (placeholders)"):
    elec = st.number_input("Electricity (USD/MWh)", min_value=0.0, value=100.0, step=5.0)
    fuel_prices = {f: st.number_input(f"{f} (USD/t)", min_value=1.0, value=p.default_price_usd_t, step=10.0)
                   for f, p in FUELS.items()}
prices = Prices(elec, fuel_prices)

with st.sidebar.expander("Anomaly detection"):
    settings = A.AnomalySettings(
        drift_threshold=st.slider("Drift threshold", 0.02, 0.10, 0.04, 0.01, format="%.2f"),
        baseline_days=st.slider("Baseline window (days)", 30, 120, 60, 10),
        low_load=st.slider("Low-load flag below", 0.1, 0.5, 0.3, 0.05),
    )

# ------------------------------------------------------------------ prepare
enriched_all = enrich(daily_all, dataset.registry, prices)
in_ships = enriched_all[enriched_all["ship_name"].isin(ships)]
# Anomaly baselines need history before the window: compute on all dates.
anomalies = A.detect_anomalies(in_ships, settings)
baseline = A.efficiency_baseline(in_ships, settings)
events = A.downtime_events(enriched_all, prices)
mask = (in_ships["date"] >= pd.Timestamp(start)) & (in_ships["date"] <= pd.Timestamp(end))

try:
    mode = st.context.theme.type or "light"
except Exception:  # older Streamlit
    mode = "light"

ctx = V.ViewContext(
    dataset=dataset, enriched=in_ships[mask], enriched_all=enriched_all, events=events,
    anomalies=anomalies, baseline=baseline, prices=prices, theme=C.Theme(mode, order),
    freq=FREQS[freq_label], freq_label=freq_label, start=start, end=end, settings=settings,
    profiles=profiles,
)

# ------------------------------------------------------------------ page
st.title("Fleet operations & optimisation")
st.caption(f"Source: **{source}** · {len(dataset.records):,} records · "
           f"{dataset.records['ship_name'].nunique()} ships · {dmin:%d %b %Y} – {dmax:%d %b %Y}")
for w in warnings:
    st.warning(w)
if flash := st.session_state.pop("flash", None):
    st.success(flash)

tabs = st.tabs(["Fleet overview", "Ship comparison", "Ship drill-down", "Downtime & anomalies", "Data & simulation"])
with tabs[0]:
    V.fleet_overview(ctx)
with tabs[1]:
    V.ship_comparison(ctx)
with tabs[2]:
    V.ship_drilldown(ctx)
with tabs[3]:
    V.downtime_and_anomalies(ctx)
with tabs[4]:
    V.data_and_simulation(ctx, add_manual_record)
