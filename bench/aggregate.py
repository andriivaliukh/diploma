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

sys.path.insert(0, str(Path(__file__).parent / "lib"))
from summarize import compute_stats, parse_iperf3_json_streams

SCENARIOS = ["no-vpn", "wg-plain", "wg-2fa", "openvpn"]
SCENARIO_LABELS = {
    "no-vpn":   "Без VPN (базовий)",
    "wg-plain": "WireGuard plain (kernel)",
    "wg-2fa":   "Ця система (WG + 2FA)",
    "openvpn":  "OpenVPN (AES-256-CBC)",
}
TODO = r"\TODO{fill in after measurement campaign}"
NA = "N/A"


def load_csv(path: Path) -> list:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def aggregate_cells(rows: list, expected_n: int = 5) -> dict:
    """Group rows by (scenario, metric); compute cross-run stats from value column.

    Cross-run stddev is recomputed from values — NOT averaged from per-row stddev.
    Returns dict[(scenario, metric)] → {n, mean, median, stddev, p95, notes}.
    If len(values) < expected_n, notes = "only N/M runs".
    """
    groups = {}
    for r in rows:
        key = (r["scenario"], r["metric"])
        groups.setdefault(key, []).append(float(r["value"]))

    result = {}
    for key, values in groups.items():
        stats = compute_stats(values)
        notes = "" if len(values) >= expected_n else f"only {len(values)}/{expected_n} runs"
        result[key] = {**stats, "notes": notes}
    return result


def _fmt_lat(cell) -> str:
    if cell is None:
        return TODO
    return f"{cell['median']:.3f} ± {cell['stddev']:.3f}"


def _fmt_p95(cell) -> str:
    if cell is None:
        return TODO
    return f"{cell['p95']:.3f}"


def _fmt_tput(cell) -> str:
    if cell is None:
        return TODO
    return f"{cell['median']:.1f} ± {cell['stddev']:.1f}"


def _fmt_cpu(cell) -> str:
    if cell is None:
        return TODO
    return f"{cell['median']:.2f} ± {cell['stddev']:.2f}"


def _fmt_onboard(cell) -> str:
    if cell is None:
        return TODO
    return str(int(round(cell["median"])))


def _n_runs(cell) -> str:
    if cell is None:
        return "0"
    return str(cell["n"])


def load_per_stream_data(data_dir: Path) -> dict:
    """Scan data_dir for *-tcp_p-json-run*.json; return per-scenario stream lists.

    Returns dict[scenario] → list[list[float]] where each inner list is
    per-stream Mbps for one run (from parse_iperf3_json_streams).
    Files that fail to parse are skipped silently.
    """
    result = {}
    for f in sorted(data_dir.glob("*-tcp_p-json-run*.json")):
        parts = f.stem.split("-tcp_p-json-run")
        if len(parts) != 2:
            continue
        scenario = parts[0]
        try:
            data = parse_iperf3_json_streams(f.read_text())
        except (ValueError, OSError):
            continue
        result.setdefault(scenario, []).append(data["per_stream"])
    return result


def _render_per_stream_section(per_stream_data: dict) -> str:
    n_streams = max(len(runs[0]) for runs in per_stream_data.values() if runs)
    header_parts = [f"Stream {i + 1}" for i in range(n_streams)] + ["SUM (Mbps)"]
    lines = []
    lines.append("## Розбалансованість потоків (Per-stream balance, tcp_p)\n")
    lines.append("| Scenario | " + " | ".join(header_parts) + " |")
    lines.append("|---" + "|---" * (n_streams + 1) + "|")
    for scen in SCENARIOS:
        runs = per_stream_data.get(scen)
        if not runs:
            continue
        cols = []
        for i in range(n_streams):
            vals = [r[i] for r in runs if i < len(r)]
            s = compute_stats(vals)
            cols.append(f"{s['mean']:.1f} ± {s['stddev']:.1f}")
        sum_stats = compute_stats([sum(r) for r in runs])
        cols.append(f"{sum_stats['mean']:.1f} ± {sum_stats['stddev']:.1f}")
        lines.append("| " + SCENARIO_LABELS[scen] + " | " + " | ".join(cols) + " |")
    lines.append("")
    return "\n".join(lines)


def render_tables(cells: dict, per_stream_data: dict = None) -> str:
    def get(scenario, metric):
        return cells.get((scenario, metric))

    lines = []

    lines.append("## Затримка (Latency)\n")
    lines.append(
        "| Scenario | lat_idle med ± stddev (ms) | lat_idle p95 (ms)"
        " | lat_load p95 (ms) | onboard (ms) | n_runs |"
    )
    lines.append("|---|---|---|---|---|---|")
    for scen in SCENARIOS:
        lat = get(scen, "lat_idle")
        ll = get(scen, "lat_load")
        ob = get(scen, "onboard")
        row = [
            SCENARIO_LABELS[scen],
            _fmt_lat(lat),
            _fmt_p95(lat),
            _fmt_p95(ll),
            NA if scen == "no-vpn" else _fmt_onboard(ob),
            _n_runs(lat),
        ]
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    lines.append("## Пропускна здатність (Throughput)\n")
    lines.append("| Scenario | tcp_t (Mbps) | tcp_p (Mbps) | udp (Mbps) | n_runs |")
    lines.append("|---|---|---|---|---|")
    for scen in SCENARIOS:
        tt = get(scen, "tcp_t")
        tp = get(scen, "tcp_p")
        ud = get(scen, "udp")
        row = [
            SCENARIO_LABELS[scen],
            _fmt_tput(tt),
            _fmt_tput(tp),
            _fmt_tput(ud),
            _n_runs(tt),
        ]
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    lines.append("## CPU (%soft / %CPU)\n")
    lines.append("| Scenario | cpu_tcp_t (%) | cpu_tcp_p (%) | n_runs |")
    lines.append("|---|---|---|---|")
    for scen in ["wg-plain", "wg-2fa", "openvpn"]:
        ct = get(scen, "cpu_tcp_t")
        cp = get(scen, "cpu_tcp_p")
        row = [SCENARIO_LABELS[scen], _fmt_cpu(ct), _fmt_cpu(cp), _n_runs(ct)]
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    if per_stream_data:
        lines.append(_render_per_stream_section(per_stream_data))

    return "\n".join(lines)


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

    cells = aggregate_cells(rows)
    per_stream_data = load_per_stream_data(csv_path.parent)
    output = render_tables(cells, per_stream_data)

    print(output)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(output)
    print(f"Written to {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
