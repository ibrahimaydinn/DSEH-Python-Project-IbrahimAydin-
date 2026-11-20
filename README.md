# Powership Efficiency Calculator

A small Streamlit web app that calculates the fuel efficiency and operating
margin of powerships for a selected ship and date, using daily production
(MWh) and fuel consumption (tons).

## Formulas

| Metric | Formula |
|---|---|
| Efficiency | `production_mwh / fuel_consumption_ton` (MWh per ton) |
| Revenue | `production_mwh × electricity_price` |
| Fuel cost | `fuel_consumption_ton × fuel_price` |
| Profit | `revenue − fuel cost` |
| Margin | `profit / revenue` |
| Break-even price | `fuel_price / efficiency` (USD/MWh) |

Fuel and electricity prices are **not** in the dataset. They are adjustable
inputs in the sidebar, with placeholder defaults (450 USD/ton, 100 USD/MWh).
Only fuel cost is included; charter, crew and maintenance costs are not.

## Data

`data/powership_veri.xlsx` with columns:
`ship_name`, `date`, `production_mwh`, `fuel_consumption_ton`.

- Rows with missing production or fuel values are excluded.
- If a ship has several records on one date, they are combined
  (total MWh / total fuel) and also listed individually.

## Project structure

```
├── app.py               # Streamlit interface
├── src/
│   ├── data.py          # loading and cleaning
│   └── calculations.py  # efficiency and profit formulas
├── data/                # input Excel file
├── requirements.txt
└── README.md
```

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

The app opens at http://localhost:8501.
