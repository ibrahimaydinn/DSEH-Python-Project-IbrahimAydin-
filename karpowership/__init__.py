"""
karpowership - a small library to monitor and analyse a fleet of powerships.

The package is organised in modules, each one with a single responsibility:

- ``fleet``        : fixed information about each ship (capacity, site, design efficiency)
- ``data``         : load, clean and reshape the daily records (pandas)
- ``simulation``   : generate realistic mock data for 2024 - November 2026
- ``calculations`` : the formulas (efficiency, capacity factor, availability, profit)
- ``alerts``       : downtime periods, efficiency alerts, fuel savings, data checks
- ``analysis``     : statistics computed with numpy and scipy
- ``plots``        : charts built with matplotlib

There is no Streamlit code in this package: the same functions are used by the
web app (``app.py`` and ``pages/``) and by the notebook (``notebooks/``).
"""

__version__ = "1.0.0"
