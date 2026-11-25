# Karpowership Fleet Dashboard

A Streamlit prototype to monitor a fleet of powerships (floating power plants):
how much energy they produce, how much fuel they burn, how efficient they are,
and when and why they are down. The data covers **1 January 2024 to
30 November 2026**: the real records plus simulated (mock) data.

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py          # opens http://localhost:8501
pytest                        # runs the tests
```

## The data

Each row is one ship on one day:

| Column | Meaning |
|---|---|
| `ship_name`, `date` | which ship, which day |
| `production_mwh` | electricity produced |
| `fuel_consumption_ton` | fuel burned (HFO) |
| `status` | `operating`, `ramp_up`, `maintenance`, `outage`, `idle` or `no_data` (optional) |
| `event_note` | short explanation, e.g. *Outage: crankshaft failure (day 3/45)* (optional) |
| `source` | `original`, `simulated` or `manual` (optional) |

The first four columns come from the original file `data/powership_veri.xlsx`
(3 ships, January–March 2024). The other columns are optional: if they are
missing, the app fills them in.

`data/powership_sim.xlsx` is the full dashboard dataset (`build_dataset` in
`src/simulation.py`):

| Period | Where it comes from |
|---|---|
| 2024 | The original records (Jan–Mar) and the 2024 simulation (Apr–Dec), with 4 fictional ships added |
| 2025 – Nov 2026 | `generate_2025_2026`: every ship continues with its 2024 behaviour |

Ship information (capacity, site, design efficiency) is in `src/fleet.py`.
The capacities are assumptions.

## The formulas (`src/calculations.py`)

| Metric | Formula |
|---|---|
| Efficiency | MWh produced ÷ tonnes of fuel |
| Capacity factor | MWh produced ÷ (capacity MW × 24 h) |
| Availability | days the ship could produce ÷ days with a report |
| Fuel cost | tonnes × fuel price |
| Revenue | MWh × electricity price |
| Profit | revenue − fuel cost |
| CO₂ | tonnes of fuel × 3.114 |

For a week or a month, the totals are divided (total MWh ÷ total fuel), never
averaged day by day. A ship that is down for a whole month has an efficiency of
0 that month: it burned standby fuel but produced nothing.

Prices are placeholders you can change in the sidebar. Only fuel cost is counted.

## The simulation (`src/simulation.py`)

For each simulated day:

```
load        = average load × season + random noise
production  = load × capacity × 24 h
efficiency  = average efficiency + random noise
fuel        = production ÷ efficiency
```

The average load and efficiency of the original three ships are learned from
their real records.

Events change the normal days:
- **Warning period (breakdowns only):** in the 3 weeks before the failure,
  efficiency slowly drops by up to 9 %.
- **Downtime:** no production, only 2–4 t/day of standby fuel.
- **Restart:** production climbs back to normal over 7 days.
- **Routine maintenance:** 5 days, roughly every 150 days.
- **Missing reports:** about 3 % of days have no data.

Two scenarios are built into the data:

| Ship | Dates | What happens |
|---|---|---|
| Rauf Bey | 1 Jul – 14 Aug 2024 (45 days) | Breakdown (`outage`): 0 MWh, 2–4 t/day standby fuel, efficiency drops in the 3 weeks before |
| Nilüfer Sultan | 29 Jan – 17 Mar 2026 (48 days) | Waiting idle offshore (`idle`): exactly 0 MWh, only 0.5–1.0 t/day of fuel for heating and maintenance on board |

Create a dataset from the command line:

```bash
python scripts/generate_mock_data.py                                    # dashboard data, 2024 - Nov 2026
python scripts/generate_mock_data.py --only-2024                        # 2024 only
python scripts/generate_mock_data.py --outage "Kaya Bey" 2024-09-02 30  # other breakdown in 2024
```

## Alerts (`src/analytics.py`)

- **Downtime periods:** consecutive days a ship was down. Energy not produced =
  days down × the ship's usual daily output.
- **Efficiency alert:** a ship's last-7-days efficiency is more than 4 % below
  its normal level (median of the previous 60 days). For Rauf Bey this fires
  16 days before the breakdown, as an early warning.
- **Fuel savings:** extra fuel burned because a ship ran below its design
  efficiency.
- **Data checks:** missing values, duplicate records, days above maximum output.

## The dashboard

Choose the ships, dates, grouping (week or month) and prices in the sidebar,
then click **Show selected data**. Nothing is shown before the first click, and
changes are only applied when the button is clicked again.

The theme is light and minimal (`.streamlit/config.toml`). The top-right
toolbar and the download / fullscreen buttons on charts and tables are hidden.

| Tab | Shows |
|---|---|
| Fleet overview | Warning box for long downtimes, 8 key numbers, energy per ship, fleet efficiency and availability, status of each ship per day |
| Compare ships | Table per ship, efficiency and capacity factor over time |
| Ship details | One ship: daily production, efficiency vs normal, downtime, single-day lookup |
| Downtime & alerts | Downtime list, efficiency alerts, fuel savings, data checks |
| Data | Add a record, download Excel/CSV, see all records |

## Files

```
app.py                         # the page: sidebar, data preparation, tabs
src/fleet.py                   # ship list
src/data.py                    # load, clean, combine, export
src/calculations.py            # formulas
src/simulation.py              # mock data generator
src/analytics.py               # downtime, alerts, savings, data checks
src/charts.py                  # charts with shaded downtime
src/views.py                   # what each tab shows
scripts/generate_mock_data.py  # command-line generator
tests/test_pipeline.py         # tests
data/                          # Excel files
```
