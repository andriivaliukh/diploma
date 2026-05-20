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


def parse_iperf3_sender_mbps(text: str) -> float:
    """Return sender Mbits/sec from iperf3 stdout (last sender line wins).

    Works for single-stream (tcp_t) and multi-stream (tcp_p [SUM] line).
    Raises ValueError if no sender line with a Mbits/sec value is found.
    """
    last_mbps = None
    for line in text.splitlines():
        if re.search(r'\bsender\b', line):
            m = re.search(r'(\d+(?:\.\d+)?)\s+Mbits/sec', line)
            if m:
                last_mbps = float(m.group(1))
    if last_mbps is None:
        raise ValueError("No sender line with Mbits/sec found in iperf3 output")
    return last_mbps


def parse_mpstat_soft_pct(text: str) -> float:
    """Return %soft from the 'Average: all' row of mpstat -P ALL output.

    Anchors column position on the header line that contains 'CPU' and '%soft',
    so it is robust to multi-CPU output (ignores per-CPU Average rows).
    Raises ValueError if no such row is found.
    """
    soft_col = None
    for line in text.splitlines():
        parts = line.split()
        if not parts or parts[0] != "Average:":
            continue
        if len(parts) > 1 and parts[1] == "CPU" and "%soft" in parts:
            soft_col = parts.index("%soft")
        elif soft_col is not None and len(parts) > 1 and parts[1] == "all":
            return float(parts[soft_col])
    raise ValueError("No 'Average: all' row with %soft column found in mpstat output")


def parse_pidstat_cpu_pct(text: str) -> float:
    """Return mean %CPU from the Average: row of pidstat -p <pid> 1 N output.

    Strategy A (strip-prefix-then-index): strips leading time tokens
    (hh:mm:ss + optional AM/PM) from the column-header line to obtain the
    data-column list, finds %CPU's index there, then strips the single
    'Average:' token from the Average: data row and reads the same index.
    Robust to AM/PM vs 24-hour formats and to column reorderings.
    Raises ValueError if no valid Average: data row is found.
    """
    cpu_data_idx = None
    for line in text.splitlines():
        parts = line.split()
        if not parts or parts[0] == "Average:":
            continue
        if "%CPU" not in parts:
            continue
        i = 0
        while i < len(parts) and (
            re.match(r'^\d+:\d+:\d+$', parts[i]) or parts[i] in ("AM", "PM")
        ):
            i += 1
        data_cols = parts[i:]
        if "%CPU" in data_cols:
            cpu_data_idx = data_cols.index("%CPU")
            break

    if cpu_data_idx is None:
        raise ValueError("No %CPU column found in pidstat header")

    for line in text.splitlines():
        parts = line.split()
        if parts and parts[0] == "Average:":
            data_cols = parts[1:]
            if len(data_cols) > cpu_data_idx:
                try:
                    return float(data_cols[cpu_data_idx])
                except ValueError:
                    continue
    raise ValueError("No Average: data row with %CPU value found in pidstat output")


def parse_udp_ramp(text: str) -> tuple:
    """Parse concatenated iperf3 UDP ramp output; return (rate_mbps, notes).

    Scans receiver summary lines (lines containing 'receiver' with both a
    Mbits/sec value and a loss% field).  Applies first->last order:
    - If first band loss > 1.0%: return (0.0, "first-step-lossy").
    - If a band with loss > 1.0% is found after clean bands: return
      (last_clean_rate, "").
    - If all bands are clean (loss ≤ 1.0%): return (last_clean_rate,
      "no-loss-at-top").
    Exactly 1.0% loss is treated as clean (condition is strictly > 1.0).
    Raises ValueError if no receiver summary lines are found.
    """
    last_clean_rate = None
    found_any = False
    for line in text.splitlines():
        if not re.search(r'\breceiver\b', line):
            continue
        m_rate = re.search(r'(\d+(?:\.\d+)?)\s+Mbits/sec', line)
        m_loss = re.search(r'\(([\d.]+)%\)', line)
        if not (m_rate and m_loss):
            continue
        found_any = True
        rate = float(m_rate.group(1))
        loss_pct = float(m_loss.group(1))
        if loss_pct <= 1.0:
            last_clean_rate = rate
        else:
            if last_clean_rate is None:
                return (0.0, "first-step-lossy")
            return (last_clean_rate, "")
    if not found_any:
        raise ValueError("No UDP receiver summary lines found in iperf3 output")
    if last_clean_rate is None:
        return (0.0, "first-step-lossy")
    return (last_clean_rate, "no-loss-at-top")


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


def summarize_tcp_t(raw_path: str, scenario: str, metric: str, run: int,
                    notes: str = "") -> list:
    text = Path(raw_path).read_text()
    mbps = parse_iperf3_sender_mbps(text)
    stats = compute_stats([mbps])
    return [
        _ts_now(), scenario, metric, run,
        f"{stats['median']:.3f}", "mbps",
        f"{stats['median']:.3f}", f"{stats['p95']:.3f}",
        f"{stats['stddev']:.3f}", f"{stats['mean']:.3f}",
        stats["n"], notes,
    ]


def summarize_tcp_p(raw_path: str, scenario: str, metric: str, run: int,
                    notes: str = "") -> list:
    text = Path(raw_path).read_text()
    mbps = parse_iperf3_sender_mbps(text)
    stats = compute_stats([mbps])
    return [
        _ts_now(), scenario, metric, run,
        f"{stats['median']:.3f}", "mbps",
        f"{stats['median']:.3f}", f"{stats['p95']:.3f}",
        f"{stats['stddev']:.3f}", f"{stats['mean']:.3f}",
        stats["n"], notes,
    ]


def summarize_lat_load(raw_path: str, scenario: str, metric: str, run: int,
                       notes: str = "") -> list:
    text = Path(raw_path).read_text()
    rtts = parse_ping_rtts(text)
    if not rtts:
        raise ValueError(f"No RTT samples in {raw_path}")
    stats = compute_stats(rtts)
    return [
        _ts_now(), scenario, metric, run,
        f"{stats['p95']:.3f}", "ms",
        f"{stats['median']:.3f}", f"{stats['p95']:.3f}",
        f"{stats['stddev']:.3f}", f"{stats['mean']:.3f}",
        stats["n"], notes,
    ]


def summarize_udp(raw_path: str, scenario: str, metric: str, run: int,
                  notes: str = "") -> list:
    text = Path(raw_path).read_text()
    rate, parser_note = parse_udp_ramp(text)
    if notes and parser_note:
        full_notes = f"{notes}|{parser_note}"
    else:
        full_notes = notes or parser_note
    return [
        _ts_now(), scenario, metric, run,
        f"{rate:.3f}", "mbps_below_1pct_loss",
        f"{rate:.3f}", f"{rate:.3f}",
        "0.000", f"{rate:.3f}",
        1, full_notes,
    ]


def summarize_cpu_tcp_t(raw_path: str, scenario: str, metric: str, run: int,
                        notes: str = "") -> list:
    text = Path(raw_path).read_text()
    if scenario in ("wg-plain", "wg-2fa"):
        pct = parse_mpstat_soft_pct(text)
    elif scenario == "openvpn":
        pct = parse_pidstat_cpu_pct(text)
    else:
        raise ValueError(f"cpu_tcp_t not supported for scenario '{scenario}'")
    return [
        _ts_now(), scenario, metric, run,
        f"{pct:.3f}", "pct",
        f"{pct:.3f}", f"{pct:.3f}",
        "0.000", f"{pct:.3f}",
        1, notes,
    ]


_SUMMARIZERS = {
    "lat_idle": summarize_lat_idle,
    "tcp_t": summarize_tcp_t,
    "tcp_p": summarize_tcp_p,
    "lat_load": summarize_lat_load,
    "udp": summarize_udp,
    "cpu_tcp_t": summarize_cpu_tcp_t,
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
