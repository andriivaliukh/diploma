#!/usr/bin/env python3
"""
aggregate.py — post-processor: results.csv → markdown tables for §3.10.

Runs on the laptop after rsync-back from VPS B:
    rsync root@94.237.94.30:/root/data/benchmarks/ ./data/benchmarks/
    python3 bench/aggregate.py

Output: printed to stdout AND written to data/benchmarks/tables-for-thesis.md.
Each table row is median ± stddev formatted, scenario-by-scenario.
"""
import argparse
import csv
import sys
from pathlib import Path

SCENARIOS = ["no-vpn", "wg-plain", "wg-2fa", "openvpn"]
SCENARIO_LABELS = {
    "no-vpn":   "Без VPN (базовий)",
    "wg-plain": "WireGuard plain (kernel)",
    "wg-2fa":   "Ця система (WG + 2FA)",
    "openvpn":  "OpenVPN (AES-256-CBC)",
}


def load_csv(path: Path) -> list:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def cell_rows(rows: list, scenario: str, metric: str) -> list:
    return [r for r in rows if r["scenario"] == scenario and r["metric"] == metric]


def cross_run_stats(values: list) -> dict:
    if not values:
        return {}
    n = len(values)
    mean = sum(values) / n
    sorted_v = sorted(values)
    mid = n // 2
    median = sorted_v[mid] if n % 2 == 1 else (sorted_v[mid-1] + sorted_v[mid]) / 2.0
    variance = sum((x - mean) ** 2 for x in values) / n
    stddev = variance ** 0.5
    return {"mean": mean, "median": median, "stddev": stddev, "n": n}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate bench results.csv → §3.10 markdown tables"
    )
    parser.add_argument(
        "--csv",
        default="data/benchmarks/results.csv",
        help="Input CSV (default: data/benchmarks/results.csv)",
    )
    parser.add_argument(
        "--out",
        default="data/benchmarks/tables-for-thesis.md",
        help="Output markdown (default: data/benchmarks/tables-for-thesis.md)",
    )
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"ERROR: {csv_path} not found. Run bench/run.sh first.", file=sys.stderr)
        return 1

    rows = load_csv(csv_path)
    if not rows:
        print("ERROR: results.csv is empty.", file=sys.stderr)
        return 1

    # TODO (commit 2): implement full aggregation and table generation.
    print("aggregate.py skeleton — full aggregation not yet implemented.", file=sys.stderr)
    print(f"Loaded {len(rows)} rows from {csv_path}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
