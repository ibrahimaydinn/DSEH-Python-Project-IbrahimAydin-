"""Create the simulated dataset from the command line.

Examples:
    python scripts/generate_mock_data.py
    python scripts/generate_mock_data.py --end 2025-06-30 --out data/sim_2025.xlsx
    python scripts/generate_mock_data.py --outage "Kaya Bey" 2024-09-02 30
    python scripts/generate_mock_data.py --no-outage --no-new-ships
    python scripts/generate_mock_data.py --base data/powership_sim.xlsx --end 2025-03-31 --no-outage
"""
import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so "src" can be imported

from src.data import ORIGINAL_FILE, SIMULATED_FILE, load_file, save_excel  # noqa: E402
from src.simulation import DEFAULT_EVENT, Event, generate_fleet  # noqa: E402

parser = argparse.ArgumentParser(description="Generate mock powership data.")
parser.add_argument("--base", default=ORIGINAL_FILE, help="real records to keep and continue")
parser.add_argument("--end", type=date.fromisoformat, default=date(2024, 12, 31), help="last day (YYYY-MM-DD)")
parser.add_argument("--outage", nargs=3, metavar=("SHIP", "START", "DAYS"), help="breakdown to simulate")
parser.add_argument("--no-outage", action="store_true", help="no breakdown, only routine maintenance")
parser.add_argument("--no-new-ships", action="store_true", help="only the ships in the base file")
parser.add_argument("--seed", type=int, default=42)
parser.add_argument("--out", default=SIMULATED_FILE, help=".xlsx or .csv")
args = parser.parse_args()

if args.no_outage:
    events = []
elif args.outage:
    ship, start, days = args.outage
    events = [Event(ship, date.fromisoformat(start), int(days))]
else:
    events = [DEFAULT_EVENT]

records = generate_fleet(load_file(args.base), args.end, events, new_ships=not args.no_new_ships, seed=args.seed)

if str(args.out).endswith(".csv"):
    records.assign(date=records["date"].dt.date).to_csv(args.out, index=False)
else:
    save_excel(records, args.out)

print(records.groupby("ship_name")["date"].agg(["min", "max", "count"]))
print(records["status"].value_counts())
print(f"Saved {len(records)} records to {args.out}")
