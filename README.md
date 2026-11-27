# Karpowership Fleet Dashboard

Karpowership Fleet Dashboard monitors a fleet of powerships (floating power plants):
how much energy they produce, how much fuel they burn, how efficient they are, and
when and why they stop. It can be explored in a web app or in a notebook.

![Streamlit app](https://img.shields.io/badge/built%20with-Streamlit-ff4b4b)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)

## What the app does

Choose the ships, the dates and the prices in the sidebar, then click
**Show selected data**. The app has five pages:

| Page | What you can see |
|------|------------------|
| **Fleet overview** (`pages/overview.py`) | Eight key numbers, the energy produced each month, the fleet availability and a ship-by-month availability heatmap. |
| **Ships** (`pages/ships.py`) | A table comparing the ships, a ranking chart, and one ship in detail: daily production and efficiency compared with its normal level. |
| **Statistics** (`pages/statistics.py`) | Efficiency statistics per ship, the seasonal pattern, efficiency trends (linear regression) and a t-test on the efficiency before each long downtime. |
| **Downtime and alerts** (`pages/downtime.py`) | Every downtime period with the energy and revenue lost, the efficiency alerts, the fuel-savings potential and data-quality checks. |
| **Data** (`pages/data.py`) | Add a record by hand, download all records as CSV, browse the table. |

### The main formulas

| Metric | Formula |
|--------|---------|
| Efficiency | MWh produced ÷ tonnes of fuel |
| Capacity factor | MWh produced ÷ (capacity MW × 24 h) |
| Availability | days the ship could produce ÷ days with a report |
| Profit | MWh × electricity price − tonnes × fuel price |
| CO₂ | tonnes of fuel × 3.114 |

Over a month or a year, totals are divided (total MWh ÷ total fuel), never averaged
day by day. All formulas live in [`karpowership/calculations.py`](karpowership/calculations.py).

## Data

- **`data/powership_veri.xlsx`**: the real records: 3 ships (Doğan Bey, Kaya Bey,
  Rauf Bey), one row per ship and day, January – March 2024. Columns: `ship_name`,
  `date`, `production_mwh`, `fuel_consumption_ton`. Some days are missing and some
  have two records.
- **`data/powership_data.csv`**: the dataset used by the app, 1 January 2024 –
  30 November 2026. It keeps the real records and adds realistic mock data
  ([`karpowership/simulation.py`](karpowership/simulation.py)): 4 more ships,
  seasonal demand, routine maintenance and missing reports. Extra columns:
  `status` (`operating`, `ramp_up`, `maintenance`, `outage`, `idle`, `no_data`),
  `event_note` and `source`.

Two scenarios are built into the data:

| Ship | Dates | What happens |
|------|-------|--------------|
| Rauf Bey | 1 Jul – 14 Aug 2024 (45 days) | Engine breakdown: no production, 2–4 t/day standby fuel. Efficiency drops in the 3 weeks before. |
| Nilüfer Sultan | 29 Jan – 17 Mar 2026 (48 days) | Waiting idle offshore: exactly 0 MWh, only 0.5–1.0 t/day of fuel for heating and maintenance on board. |

Ship capacities (in [`karpowership/fleet.py`](karpowership/fleet.py)), prices and
the four extra ships are assumptions for this prototype.

To create the dataset again:

```bash
python -m karpowership.simulation
```

## Libraries

| Library | Used for |
|---------|----------|
| `pandas` | cleaning, combining, grouping and reshaping the records |
| `numpy` | daily metrics, percentiles, random numbers for the mock data |
| `scipy` | linear regression (`linregress`) and t-test (`ttest_ind`) |
| `matplotlib` | the charts |
| `openpyxl` | reading the original Excel file |
| `streamlit` | the web application |
| `jupyterlab` | running the walkthrough notebook |
| `pytest` | the tests |

Exact versions are listed in [`requirements.txt`](requirements.txt).

## Setup

1. Clone the repository and enter the folder:

   ```bash
   git clone https://github.com/ibrahimaydinn/DSEH-Python-Project-IbrahimAydin-.git
   cd DSEH-Python-Project-IbrahimAydin-
   ```

2. Create a virtual environment and install the dependencies (Python 3.11 or newer):

   ```bash
   python -m venv .venv
   source .venv/bin/activate        # on Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

## Run

Start the web app:

```bash
streamlit run app.py
```

The browser opens at <http://localhost:8501>. Use the sidebar to move between pages.

The package can also be used without Streamlit, like any library:

```python
from karpowership.calculations import add_daily_metrics, summarize
from karpowership.data import load_records, one_row_per_day

daily = add_daily_metrics(one_row_per_day(load_records()))
print(summarize(daily))
```

Run the tests with `pytest`.

### The walkthrough notebook

[`notebooks/karpowership_walkthrough.ipynb`](notebooks/karpowership_walkthrough.ipynb)
uses the `karpowership` package step by step: it loads and cleans the real records,
generates the full dataset, calculates the metrics, reshapes the data by month,
draws the charts, finds the downtime and alerts, runs the statistics and sums up the
conclusions. Start Jupyter from the project folder and open it:

```bash
jupyter lab
```

## Project structure

```
DSEH-Python-Project-IbrahimAydin-/
├── app.py                  # Streamlit entry point: page settings, sidebar, list of pages
├── pages/
│   ├── shared.py           # sidebar form and selected data, used by every page
│   ├── overview.py         # fleet overview
│   ├── ships.py            # comparison and one ship in detail
│   ├── statistics.py       # numpy / scipy results
│   ├── downtime.py         # downtime, alerts, savings, data checks
│   └── data.py             # add a record, download, all records
├── karpowership/           # the backend package (no Streamlit code here)
│   ├── __init__.py
│   ├── fleet.py            # ship information
│   ├── data.py             # load, clean and reshape the records (pandas)
│   ├── simulation.py       # mock data generator and scenarios
│   ├── calculations.py     # the formulas
│   ├── alerts.py           # downtime periods, efficiency alerts, savings, data checks
│   ├── analysis.py         # statistics with numpy and scipy
│   └── plots.py            # charts with matplotlib
├── data/
│   ├── powership_veri.xlsx # the real records
│   └── powership_data.csv  # the full dataset used by the app
├── notebooks/
│   └── karpowership_walkthrough.ipynb  # the analysis, step by step
├── tests/
│   └── test_pipeline.py
├── .streamlit/config.toml  # light, minimal theme
├── .gitignore
├── requirements.txt
└── README.md
```

Everything in `karpowership/` is plain Python that can be reused in a notebook or a
script, while `app.py` and `pages/` only deal with showing things on screen.
