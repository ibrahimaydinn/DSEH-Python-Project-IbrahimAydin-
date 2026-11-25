# Karowership Fleet Dashboard

A Streamlit prototype to monitor a fleet of powerships (floating power plants):
how much energy they produce, how much fuel they burn, how efficient they are,
and when and why they are down. It includes a simple simulator to create more
mock data, for example a ship that breaks down for 45 days.

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
| `status` | `operating`, `ramp_up`, `maintenance`, `outage` or `no_data` (optional) |
| `event_note` | short explanation, e.g. *Outage: crankshaft failure (day 3/45)* (optional) |
| `source` | `original`, `simulated` or `manual` (optional) |

The first four columns come from the original file `data/powership_veri.xlsx`
(3 ships, January–March 2024). The other columns are optional: if they are
missing, the app fills them in.

`data/powership_sim.xlsx` is the simulated dataset. It keeps the original rows,
continues all ships to the end of 2024, and adds 4 fictional ships.

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

**Default scenario:** Rauf Bey breaks down from 1 July to 14 August 2024
(45 days). The sidebar lets you pick another ship, type, start date or length.

Create a dataset from the command line:

```bash
python scripts/generate_mock_data.py                                    # default
python scripts/generate_mock_data.py --outage "Kaya Bey" 2024-09-02 30  # other breakdown
python scripts/generate_mock_data.py --base data/powership_sim.xlsx --end 2025-03-31 --no-outage
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
