#!/usr/bin/env python3
"""
summarize.py — parse one raw metric file → emit one CSV row to stdout.

Usage (called from run.sh):
    python3 summarize.py <raw_file> <scenario> <metric> <run> [notes]

The row is appended to results.csv by the caller via shell redirection.
"""
import csv
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def parse_ping_rtts(text: str) -> list:
    """Extract RTT float values from ping stdout (time=X.X ms lines only)."""
    rtts = []
    for line in text.splitlines():
        m = re.search(r'\btime=(\d+(?:\.\d+)?)\s*ms\b', line)
        if m:
            rtts.append(float(m.group(1)))
    return rtts


def compute_stats(values: list) -> dict:
    """Return mean, median, p95, stddev, n for a float list.

    Raises ValueError on empty input.
    Uses population stddev (the run's 300 samples are the full population).
    p95 via linear interpolation.
    """
    if not values:
        raise ValueError("compute_stats requires a non-empty list")
    n = len(values)
    mean = sum(values) / n
    sorted_vals = sorted(values)
    mid = n // 2
    if n % 2 == 1:
        median = sorted_vals[mid]
    else:
        median = (sorted_vals[mid - 1] + sorted_vals[mid]) / 2.0
    idx = 0.95 * (n - 1)
    lo = int(idx)
    hi = lo + 1
    if hi >= n:
        p95 = sorted_vals[-1]
    else:
        p95 = sorted_vals[lo] + (idx - lo) * (sorted_vals[hi] - sorted_vals[lo])
    variance = sum((x - mean) ** 2 for x in values) / n
    stddev = variance ** 0.5
    return {"mean": mean, "median": median, "p95": p95, "stddev": stddev, "n": n}


def _ts_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def summarize_lat_idle(raw_path: str, scenario: str, metric: str, run: int,
                       notes: str = "") -> list:
    text = Path(raw_path).read_text()
    rtts = parse_ping_rtts(text)
    if not rtts:
        raise ValueError(f"No RTT samples in {raw_path}")
    stats = compute_stats(rtts)
    return [
        _ts_now(), scenario, metric, run,
        f"{stats['median']:.3f}", "ms",
        f"{stats['median']:.3f}", f"{stats['p95']:.3f}",
        f"{stats['stddev']:.3f}", f"{stats['mean']:.3f}",
        stats["n"], notes,
    ]


_SUMMARIZERS = {
    "lat_idle": summarize_lat_idle,
}


def main(argv: list) -> int:
    if len(argv) < 5:
        print("Usage: summarize.py <raw_file> <scenario> <metric> <run> [notes]",
              file=sys.stderr)
        return 1
    raw_file, scenario, metric, run_s = argv[1], argv[2], argv[3], argv[4]
    notes = argv[5] if len(argv) > 5 else ""
    try:
        run = int(run_s)
    except ValueError:
        print(f"ERROR: run must be an integer, got: {run_s!r}", file=sys.stderr)
        return 1

    fn = _SUMMARIZERS.get(metric)
    if fn is None:
        print(f"STUB: summarize not implemented for metric '{metric}'", file=sys.stderr)
        return 1

    try:
        row = fn(raw_file, scenario, metric, run, notes)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    writer = csv.writer(sys.stdout)
    writer.writerow(row)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
