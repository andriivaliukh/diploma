#!/usr/bin/env bash
# run.sh — Slice 2B benchmark harness orchestrator.
#
# Usage:
#   ./run.sh              # run all 4 scenarios
#   ./run.sh no-vpn       # run a single scenario
#
# Runs from VPS B; results land in <repo>/data/benchmarks/.
# aggregate.py runs on the laptop after rsync-back, not here.

set -uo pipefail

BENCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$BENCH_DIR/.." && pwd)"
DATA_DIR="$REPO_DIR/data/benchmarks"
RESULTS_CSV="$DATA_DIR/results.csv"
BENCH_MODE="${BENCH_MODE:-measure}"
N="${BENCH_N:-5}"
[[ "$BENCH_MODE" == "smoke" ]] && N=1
VPS_A="root@81.27.101.178"
PYTHON3="${BENCH_PYTHON3:-python3}"

source "$BENCH_DIR/lib/scenarios.sh"
source "$BENCH_DIR/lib/metrics.sh"

SCENARIOS=("no-vpn" "wg-plain" "wg-2fa" "openvpn")
METRICS=("lat_idle" "tcp_t" "tcp_p" "lat_load" "udp")
CSV_HEADER="ts_iso,scenario,metric,run,value,unit,median,p95,stddev,mean,n_samples,notes"

CURRENT_SCENARIO=""

log()  { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; }
die()  { log "ERROR: $*"; exit 1; }
warn() { log "WARN: $*"; }

ensure_csv_header() {
    mkdir -p "$DATA_DIR"
    if [[ ! -f "$RESULTS_CSV" ]]; then
        printf '%s\n' "$CSV_HEADER" > "$RESULTS_CSV"
    fi
}

# Remove all rows for a given scenario before re-running it (idempotency).
drop_scenario_rows() {
    local scenario="$1"
    [[ ! -f "$RESULTS_CSV" ]] && return 0
    $PYTHON3 - "$RESULTS_CSV" "$scenario" <<'PYEOF'
import csv, sys
path, scenario = sys.argv[1], sys.argv[2]
with open(path) as f:
    rows = list(csv.reader(f))
header = rows[:1]
data = [r for r in rows[1:] if r and r[1] != scenario]
with open(path, 'w', newline='') as f:
    w = csv.writer(f)
    w.writerows(header + data)
PYEOF
}

run_metric_safely() {
    local scenario="$1" metric="$2" run="$3"
    local raw="$DATA_DIR/${scenario}-${metric}-run${run}.txt"

    BENCH_CURRENT_SCENARIO="$scenario"
    BENCH_CURRENT_RUN="$run"

    local cpu_pid=""
    if [[ ( "$metric" == "tcp_t" || "$metric" == "tcp_p" ) && "$scenario" != "no-vpn" ]]; then
        ssh "$VPS_A" "/opt/bench/remote_cpu_capture.sh ${scenario} ${metric} ${run}" &
        cpu_pid=$!
    fi

    if ! "run_${metric}" > "$raw" 2>&1; then
        warn "$scenario/$metric run $run: not implemented or failed — skipping"
        [[ -n "$cpu_pid" ]] && { wait "$cpu_pid" 2>/dev/null || true; }
        return 0
    fi

    if [[ -n "$cpu_pid" ]]; then
        wait "$cpu_pid" || warn "CPU capture for $scenario/$metric run $run exited non-zero"
    fi

    if ! $PYTHON3 "$BENCH_DIR/lib/summarize.py" "$raw" "$scenario" "$metric" "$run" \
            >> "$RESULTS_CSV"; then
        warn "$scenario/$metric run $run: summarize failed"
    fi
}

run_scenario() {
    local scenario="$1"
    log "=== scenario: $scenario ==="

    drop_scenario_rows "$scenario"

    if ! setup_scenario "$scenario"; then
        warn "setup_scenario $scenario failed (stub or pre-flight) — skipping scenario"
        return 0
    fi
    CURRENT_SCENARIO="$scenario"

    if [[ "$scenario" != "no-vpn" && -n "${ONBOARD_MS:-}" ]]; then
        local ts
        ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        printf '%s,%s,onboard,1,%s,ms,%s,,,,1,\n' \
            "$ts" "$scenario" "$ONBOARD_MS" "$ONBOARD_MS" >> "$RESULTS_CSV"
        log "  $scenario / onboard: ${ONBOARD_MS}ms"
    fi

    for metric in "${METRICS[@]}"; do
        if [[ "$BENCH_MODE" == "smoke" && "$metric" == "lat_load" ]]; then
            log "  $scenario / $metric: skipped in smoke mode"
            continue
        fi
        for run in $(seq 1 "$N"); do
            log "  $scenario / $metric / run $run"
            run_metric_safely "$scenario" "$metric" "$run"
        done
    done

    if [[ "$scenario" != "no-vpn" ]]; then
        rsync "${VPS_A}:/tmp/cpu-${scenario}-*.txt" "$DATA_DIR/" 2>/dev/null \
            || warn "no CPU capture files rsynced for $scenario"

        for cpu_metric in cpu_tcp_t cpu_tcp_p; do
            for run in $(seq 1 "$N"); do
                local cpu_raw="$DATA_DIR/cpu-${scenario}-${cpu_metric#cpu_}-run${run}.txt"
                if [[ -f "$cpu_raw" ]]; then
                    if ! $PYTHON3 "$BENCH_DIR/lib/summarize.py" \
                            "$cpu_raw" "$scenario" "$cpu_metric" "$run" \
                            >> "$RESULTS_CSV"; then
                        warn "$scenario/$cpu_metric run $run: summarize failed"
                    fi
                fi
            done
        done
    fi

    teardown_scenario "$scenario"
    CURRENT_SCENARIO=""
}

apply_sanity_gates() {
    [[ ! -f "$RESULTS_CSV" ]] && return 0
    $PYTHON3 - "$RESULTS_CSV" >&2 <<'PYEOF'
import csv, sys

path = sys.argv[1]
with open(path) as f:
    rows = list(csv.DictReader(f))


def get_vals(rows, scenario, metric, field):
    return [float(r[field]) for r in rows
            if r['scenario'] == scenario and r['metric'] == metric and r.get(field)]


def warn(msg):
    print(f"WARN [sanity]: {msg}")


wgp = get_vals(rows, 'wg-plain', 'tcp_t', 'value')
wg2 = get_vals(rows, 'wg-2fa', 'tcp_t', 'value')
if wgp and wg2:
    avg_wgp = sum(wgp) / len(wgp)
    avg_wg2 = sum(wg2) / len(wg2)
    if avg_wgp > 0 and abs(avg_wgp - avg_wg2) / avg_wgp > 0.05:
        warn(f"Gate 1: tcp_t wg-plain ({avg_wgp:.1f}) vs wg-2fa ({avg_wg2:.1f}) differ >5%")

for scen in ('no-vpn', 'wg-plain', 'wg-2fa', 'openvpn'):
    for v in get_vals(rows, scen, 'tcp_t', 'value'):
        if v >= 950:
            warn(f"Gate 2: {scen} tcp_t={v:.0f} Mbps >=950 (hard-flag: near 1-vCPU NIC ceiling)")
        elif v >= 900:
            warn(f"Gate 2: {scen} tcp_t={v:.0f} Mbps >=900 (approaching NIC ceiling)")

base = get_vals(rows, 'no-vpn', 'lat_idle', 'mean')
if base:
    base_mean = sum(base) / len(base)
    for scen in ('wg-plain', 'wg-2fa', 'openvpn'):
        vals = get_vals(rows, scen, 'lat_idle', 'mean')
        if vals:
            scen_mean = sum(vals) / len(vals)
            if abs(scen_mean - base_mean) > 5.0:
                warn(f"Gate 3: {scen} lat_idle mean ({scen_mean:.2f} ms) >5 ms from no-vpn ({base_mean:.2f} ms)")

for r in rows:
    try:
        mean = float(r['mean'])
        stddev = float(r['stddev'])
        if mean > 0 and stddev / mean > 0.20:
            warn(f"Gate 4: {r['scenario']}/{r['metric']}/run{r['run']} "
                 f"stddev/mean={stddev/mean:.0%} >20% — consider N=10, iperf3 -t 120")
    except (ValueError, ZeroDivisionError, KeyError):
        pass

ovpn_med = get_vals(rows, 'openvpn', 'lat_idle', 'median')
wgp_med = get_vals(rows, 'wg-plain', 'lat_idle', 'median')
if ovpn_med and wgp_med:
    delta = sum(ovpn_med) / len(ovpn_med) - sum(wgp_med) / len(wgp_med)
    if not (0 < delta <= 1.5):
        warn(f"Gate 5: openvpn-wg-plain lat_idle delta={delta:.2f} ms outside (0, 1.5] ms")
PYEOF
}

cleanup_on_exit() {
    if [[ -n "$CURRENT_SCENARIO" ]]; then
        log "EXIT trap: tearing down $CURRENT_SCENARIO"
        teardown_scenario "$CURRENT_SCENARIO" 2>/dev/null || true
        CURRENT_SCENARIO=""
    fi
}
trap cleanup_on_exit EXIT

main() {
    ensure_csv_header
    local target="${1:-all}"
    if [[ "$target" == "all" ]]; then
        for s in "${SCENARIOS[@]}"; do
            run_scenario "$s"
        done
    else
        run_scenario "$target"
    fi
    apply_sanity_gates
    log "Done. Results: $RESULTS_CSV"
}

main "$@"
