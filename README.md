# Karowership Fleet Operations & Optimisation Dashboard

A Streamlit prototype for the operations and optimisation team. It monitors a
fleet of powerships: energy produced, fuel consumed, efficiency, availability
and downtime. It also flags anomalies and sizes optimisation opportunities.
It includes a scenario simulator, so the mock dataset can be extended with
new ships, longer date ranges and operational events such as a 45-day
forced outage.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py              # http://localhost:8501
pytest                            # 20 tests
```

## Dashboard

| Tab | What it answers |
|---|---|
| **Fleet overview** | Callouts for major downtime (lost MWh, revenue, standby fuel, early-warning lead time). 10 KPI tiles with deltas vs the previous period of equal length. Stacked energy by ship with outage bands. Fleet thermal efficiency, capacity factor and availability trends. Status timeline (ship × day). |
| **Ship comparison** | KPI table per ship. Ship rankings with fleet benchmark. Efficiency-vs-load curves (dispatch optimisation). Small-multiple trends per ship with downtime shading. |
| **Ship drill-down** | Daily output coloured by status. Load-corrected efficiency vs trailing baseline with anomaly markers (brush the top chart to zoom). Event and anomaly tables. The original single-day calculator. |
| **Downtime & anomalies** | Event log with impact. Efficiency-drift episodes linked to the outage that followed (early warning). Filterable anomaly log. Fuel-savings potential per ship. |
| **Data & simulation** | Data-quality checks. Form to add a record (also for new ships). Excel/CSV export. Save to `data/powership_sim.xlsx`. Raw records, ship registry and simulation profiles. |

The sidebar holds the data source (simulator, original Excel or upload),
scenario controls, ship and date filters, granularity (daily/weekly/monthly),
fuel and electricity prices, and anomaly-detection thresholds.

## Data

### Schema

Core columns (the original contract; every file needs these):
`ship_name`, `date`, `production_mwh`, `fuel_consumption_ton`.

Optional columns, filled with defaults when absent, so the original file
loads unchanged:

| Column | Meaning | Default when missing |
|---|---|---|
| `status` | `operating`, `ramp_up`, `trip`, `planned_maintenance`, `dry_dock`, `forced_outage`, `no_data` | `operating`, or `no_data` if values are missing |
| `operating_hours` | Hours generating that day | 24 |
| `event_note` | Cause, or day *n/N* of an event | empty |
| `source` | `original`, `simulated`, `manual`, `upload` | `original` |

Excel files may include a `ships` sheet (`name`, `capacity_mw`, `fuel_type`,
`site`, `commissioned`, `design_mwh_per_ton`). Without it, specs come from
`src/fleet.py` or are inferred (P95 daily output ≈ 85 % load).

### Files

- `data/powership_veri.xlsx`: original data. 3 ships, 1 Jan – 30 Mar 2024, 24 rows with missing values, 21 ship-days with two records.
- `data/powership_sim.xlsx`: generated default. The original rows are kept as they are, then all 7 ships are simulated to 31 Dec 2024 with the Rauf Bey outage.

### Fleet

| Ship | MW | Fuel | Site | Notes |
|---|---|---|---|---|
| Doğan Bey, Kaya Bey, Rauf Bey | 25 | HFO | West Africa / Mediterranean | Original ships. Capacity is assumed. Profiles are calibrated from the Excel data. |
| Selim Bey | 36 | HFO | West Africa | High load, efficient |
| Nilüfer Sultan | 30 | LNG | Mediterranean | Strong summer peak |
| Kerem Bey | 20 | HFO | South Asia | Older: more trips, faster fouling, lower efficiency |
| Deniz Sultan | 42 | LNG | South Asia | Commissioned 15 May 2024, with ramp-up |

## Simulation model (`src/simulation`)

For each ship-day:

```
load factor = base · seasonality(peak month) · demand_scale + AR(1) noise
efficiency  = peak MWh/t · part-load curve(load) · fouling drift · hot-season derate · noise
production  = load factor · MW · 24        fuel = production / efficiency
```

The simulator also adds:
- Routine maintenance at each ship's cadence. Maintenance resets fouling.
- Random unit trips (partial days plus restart fuel).
- Missing reports.
- Explicit **downtime scenarios** (`DowntimeScenario`).

**Headline scenario: Rauf Bey forced outage, 1 Jul – 14 Aug 2024 (45 days)**
- **Before:** 21 days of efficiency decline (up to −9 %) and slight derating.
- **During:** zero output, 2–4 t/day standby fuel (hotel load, HFO heating), status `forced_outage`.
- **After:** a 7-day ramp-up.

What the dashboard shows:
- An error callout with about 14.8 GWh not generated and about $1.5 M revenue forgone.
- Rauf Bey's monthly MWh/t drops to 0 in July.
- Fleet availability falls from 100 % to 78 % and capacity factor from 69 % to 54 % (June → July).
- Fleet thermal efficiency dips.
- The drift detector flags the decline from 21 Jun, 10 days before the failure.

Other presets: Kaya Bey 45-day dry-dock; a "double hit" (Rauf Bey outage plus
a Kerem Bey overhaul); and a baseline with routine maintenance only. The
sidebar also builds custom scenarios (ship, type, start, duration, decline
period).

### Command-line generator

```bash
python scripts/generate_mock_data.py                                   # default → data/powership_sim.xlsx
python scripts/generate_mock_data.py --base data/powership_sim.xlsx --end 2025-06-30 --out data/sim_2025.xlsx
python scripts/generate_mock_data.py --outage "Kaya Bey" 2024-09-02 45 dry_dock --seed 7
python scripts/generate_mock_data.py --no-base --ships "Doğan Bey" "Kaya Bey" --out data/two.csv
```

With `--base`, the existing rows are kept and each ship continues from the
day after its last record.

### Adding scenarios or ships

- **New event:** add a `DowntimeScenario` to `PRESETS` in `src/simulation/scenarios.py`.
- **New ship:** add a `ShipSpec` in `src/fleet.py` and a `ShipProfile` in `src/simulation/profiles.py`.
- **New behaviour:** extend `simulate_ship` in `src/simulation/generator.py`, for example heat waves or fuel-quality issues.

## Formulas (`src/calculations.py`)

| Metric | Formula |
|---|---|
| Efficiency | MWh / fuel t |
| SFC | 1000 · fuel t / MWh (g/kWh) |
| Heat rate | SFC · LHV (kJ/kWh) |
| Thermal efficiency | MWh / fuel energy (LHV). Fuel-neutral, so HFO and LNG ships compare fairly |
| Load-corrected efficiency | MWh/t ÷ part-load curve(load). Used for drift detection |
| Capacity factor | MWh / (MW · 24 · reported ship-days) |
| Availability | Available ship-days / reported ship-days |
| CO₂ | Fuel t · carbon factor (HFO 3.114, LNG 2.750, MGO 3.206) |
| Revenue, fuel cost, profit, margin | As before. Fuel price is set per fuel type |
| Break-even | Fuel cost per MWh |

Totals always use the ratio of sums. A period with standby burn but no output
has 0 MWh/t, not a blank, so the dip is visible.

Prices, capacities and LHV/CO₂ factors are placeholders. Only fuel cost is
included; charter, crew and maintenance costs are not.

## Anomaly detection (`src/analytics.py`)

| Type | Rule |
|---|---|
| Efficiency drift | 7-day load-corrected efficiency more than 4 % below the trailing 60-day median (lagged 7 days) |
| Efficiency outlier | Robust z-score < −3 vs the 30-day median |
| Low load | Operating at < 30 % capacity factor |
| Standby burn | Fuel burned on a downtime day |
| Over capacity | Daily total > 102 % of nameplate. In the original file this catches same-day duplicate entries |
| Missing report | No production or fuel reported |

Thresholds are adjustable in the sidebar.

## Project structure

```
├── app.py                        # Streamlit entry: sidebar, data prep, tabs
├── src/
│   ├── schema.py                 # columns + status vocabulary
│   ├── fleet.py                  # ship registry, fuel properties
│   ├── data.py                   # load / normalise / aggregate / export
│   ├── calculations.py           # KPIs, enrichment, aggregation
│   ├── analytics.py              # anomalies, events, savings, data quality
│   ├── simulation/
│   │   ├── profiles.py           # ShipProfile + calibration
│   │   ├── scenarios.py          # DowntimeScenario, SimulationConfig, presets
│   │   └── generator.py          # simulate_ship, generate_fleet
│   └── ui/
│       ├── charts.py             # Altair chart builders
│       └── views.py              # one renderer per tab
├── scripts/generate_mock_data.py # CLI generator
├── tests/test_pipeline.py
└── data/
```
