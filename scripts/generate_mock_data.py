"""Generate or extend the mock powership dataset.

Examples
--------
Default: continue the original Excel through 2024 with the headline outage::

    python scripts/generate_mock_data.py

Extend a previously generated file to mid-2025 (existing rows kept)::

    python scripts/generate_mock_data.py --base data/powership_sim.xlsx --end 2025-06-30

Custom scenario, only the original three ships, CSV output::

    python scripts/generate_mock_data.py --ships "Doğan Bey" "Kaya Bey" "Rauf Bey" \\
        --outage "Kaya Bey" 2024-09-02 45 dry_dock --out data/three_ships.csv
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data import DATA_PATH, SIM_PATH, read_records, write_excel  # noqa: E402
from src.schema import Status  # noqa: E402
from src.simulation import DEFAULT_PRESET, PRESETS, DowntimeScenario, SimulationConfig, generate_fleet  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base", type=Path, default=DATA_PATH,
                   help="Existing dataset to keep and continue (default: original Excel). Use --no-base to start fresh.")
    p.add_argument("--no-base", action="store_true", help="Simulate everything from --start.")
    p.add_argument("--start", type=date.fromisoformat, default=date(2024, 1, 1))
    p.add_argument("--end", type=date.fromisoformat, default=date(2024, 12, 31))
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--ships", nargs="*", help="Ships to include (default: all known profiles + base ships).")
    p.add_argument("--preset", choices=list(PRESETS), default=None,
                   help=f"Scenario preset (default: '{DEFAULT_PRESET}' when starting from the original "
                        "Excel, otherwise none).")
    p.add_argument("--outage", nargs=4, action="append", metavar=("SHIP", "START", "DAYS", "KIND"),
                   help="Add a downtime event; KIND is forced_outage | planned_maintenance | dry_dock. "
                        "Replaces the preset. Repeatable.")
    p.add_argument("--demand-scale", type=float, default=1.0)
    p.add_argument("--no-maintenance", action="store_true", help="Disable routine maintenance windows.")
    p.add_argument("--no-trips", action="store_true")
    p.add_argument("--no-missing", action="store_true", help="Disable random missing reports.")
    p.add_argument("--out", type=Path, default=SIM_PATH, help=".xlsx (daily + ships sheets) or .csv")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    a = parse_args(argv)
    if a.outage:
        events = tuple(
            DowntimeScenario(ship=s, start=date.fromisoformat(st), duration_days=int(n), kind=Status(k))
            for s, st, n, k in a.outage
        )
    elif a.preset:
        events = PRESETS[a.preset]
    else:
        events = PRESETS[DEFAULT_PRESET] if (a.no_base or a.base == DATA_PATH) else ()
    config = SimulationConfig(
        start=a.start, end=a.end, seed=a.seed, ships=tuple(a.ships or ()), events=events,
        routine_maintenance=not a.no_maintenance, trips=not a.no_trips, missing_data=not a.no_missing,
        demand_scale=a.demand_scale,
    )
    base = None if a.no_base else read_records(a.base)
    result = generate_fleet(config, base=base)
    for w in result.warnings:
        print(f"warning: {w}", file=sys.stderr)

    recs = result.dataset.records
    a.out.parent.mkdir(parents=True, exist_ok=True)
    if a.out.suffix.lower() == ".csv":
        out = recs.copy()
        out["date"] = out["date"].dt.date
        out.to_csv(a.out, index=False)
    else:
        write_excel(a.out, recs, result.dataset.registry)

    summary = recs.groupby("ship_name").agg(first=("date", "min"), last=("date", "max"), rows=("date", "size"))
    print(summary.to_string())
    print(f"\nStatus counts:\n{recs['status'].value_counts().to_string()}")
    print(f"\nWrote {len(recs):,} records to {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
