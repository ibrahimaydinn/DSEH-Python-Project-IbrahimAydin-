"""
Page "Data": add a record by hand, download the data, see all records.
"""

import pandas as pd
import streamlit as st

from karpowership.data import OPERATING
from pages.shared import DATE_COLUMNS, selected_data

st.title("Data")
records = selected_data()["records"]

st.header("Add a record")
st.write("Records added here are used on every page until the app restarts. "
         "Click **Show selected data** to include a new ship in the selection.")
with st.form("add_record", clear_on_submit=True):
    ship = st.text_input("Ship name", value="Rauf Bey", help="A new name adds a new ship (25 MW by default).")
    day = st.date_input("Date", value=records["date"].max())
    mwh = st.number_input("Production (MWh)", min_value=0.0, value=350.0)
    fuel = st.number_input("Fuel (t)", min_value=0.0, value=70.0)
    status = st.selectbox("Status", [OPERATING, "ramp_up", "maintenance", "outage", "idle"])
    note = st.text_input("Note")
    if st.form_submit_button("Add"):
        st.session_state.added_records.append({
            "ship_name": ship.strip(), "date": pd.Timestamp(day), "production_mwh": mwh,
            "fuel_consumption_ton": fuel, "status": status, "event_note": note, "source": "manual",
        })
        st.rerun()

st.header("Download")
csv = records.assign(date=records["date"].dt.date).to_csv(index=False)
st.download_button("Download all records (CSV)", csv, "powership_data.csv")

st.header("All records")
st.dataframe(records, hide_index=True, column_config=DATE_COLUMNS)
